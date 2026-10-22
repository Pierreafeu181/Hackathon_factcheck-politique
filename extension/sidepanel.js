const API = window.FC_CONFIG.API_BASE;
const LABELS = {
  vrai: "Vrai", plutot_vrai: "Plutôt vrai", imprecis: "Imprécis",
  trompeur: "Trompeur", faux: "Faux", inverifiable: "Invérifiable",
};
const $ = (id) => document.getElementById(id);
let current = null; // { tabId, videoId, title, channel }

// ------------------------------------------------------------------ onglets
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
  $("tab-analyse").hidden = b.dataset.tab !== "analyse";
  $("tab-profils").hidden = b.dataset.tab !== "profils";
  if (b.dataset.tab === "profils") loadProfiles();
}));

// ------------------------------------------------------------------ vidéo courante
async function sendToTab(msg) {
  return chrome.tabs.sendMessage(current.tabId, msg);
}

async function refreshVideo() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url?.includes("youtube.com")) {
    current = null;
    $("video").textContent = "Ouvrez une vidéo YouTube…";
    return;
  }
  try {
    const info = await chrome.tabs.sendMessage(tab.id, { type: "getVideoInfo" });
    current = { tabId: tab.id, ...info };
    $("video").textContent = info.videoId ? `▶ ${info.title}` : "Pas de vidéo sur cette page.";
    if (info.channel && !$("speaker").value) $("speaker").placeholder = info.channel;
    if (info.videoId) loadCached(info.videoId);
  } catch {
    $("video").textContent = "Rechargez l'onglet YouTube (extension installée après son ouverture).";
  }
}
chrome.tabs.onActivated.addListener(refreshVideo);
chrome.tabs.onUpdated.addListener((_id, change) => change.url && refreshVideo());
refreshVideo();

async function loadCached(videoId) {
  const r = await fetch(`${API}/videos/${videoId}/claims`).catch(() => null);
  if (r?.ok) render(await r.json(), "Résultats déjà en base.");
  else { $("results").innerHTML = ""; $("stats").innerHTML = ""; $("status").textContent = ""; }
}

// ------------------------------------------------------------------ analyse
$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    video_id: current?.videoId || null,
    speaker: { name: $("speaker").value.trim(), party: $("party").value.trim() || null },
    title: current?.title || null,
    date: $("date").value || null,
    force: $("force").checked,
  };
  if ($("manual").value.trim()) body.transcript = $("manual").value.trim();
  else if ($("useDom").checked && current) {
    const { segments } = await sendToTab({ type: "getDomTranscript" });
    if (!segments?.length) return status("Ouvrez d'abord le panneau « Transcription » sous la vidéo YouTube.");
    body.transcript = segments;
  }
  if (!body.video_id && !body.transcript) return status("Aucune vidéo ni transcript.");

  $("go").disabled = true;
  status("Analyse en cours… (extraction puis vérification, 30 s à 2 min)");
  try {
    const r = await fetch(`${API}/analyze`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.statusText);
    render(data, `${data.results.length} affirmation(s) vérifiée(s).`);
  } catch (err) {
    status(`Erreur : ${err.message}. Le backend tourne-t-il sur ${API} ?`);
  } finally {
    $("go").disabled = false;
  }
});

function status(t) { $("status").textContent = t; }

// ------------------------------------------------------------------ rendu
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtTime(t) {
  const s = Math.floor(t || 0);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function render(data, msg) {
  status(msg);
  $("stats").innerHTML = Object.entries(data.stats || {})
    .map(([v, n]) => `<span class="badge" style="--c:var(--${v})">${LABELS[v]} · ${n}</span>`).join("");
  $("results").innerHTML = data.results.map(({ claim: c, verification: v }) => `
    <li class="card" style="--c:var(--${v.verdict})">
      ${c.timestamp_start != null ? `<span class="ts" data-t="${c.timestamp_start}">${fmtTime(c.timestamp_start)}</span>` : ""}
      <span class="badge">${LABELS[v.verdict]}</span>
      <div class="quote">« ${esc(c.quote)} »</div>
      <div>${esc(v.explanation)}</div>
      ${v.correction ? `<div class="correction">✎ ${esc(v.correction)}</div>` : ""}
      ${v.sources?.length ? `<ul class="sources">${v.sources.map((s) =>
        `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.publisher)} — ${esc(s.title)}</a>${s.note ? ` <span class="muted">(${esc(s.note)})</span>` : ""}</li>`).join("")}</ul>` : ""}
      <div class="meta">${v.method === "referentiel" ? "Données officielles" : v.method === "web" ? "Recherche web" : "—"} · confiance ${Math.round((v.confidence || 0) * 100)} %</div>
    </li>`).join("");
  document.querySelectorAll(".ts").forEach((el) =>
    el.addEventListener("click", () => sendToTab({ type: "seek", t: Number(el.dataset.t) })));
}

async function loadProfiles() {
  const r = await fetch(`${API}/politicians`).catch(() => null);
  if (!r?.ok) { $("profiles").innerHTML = `<li class="muted">Backend injoignable.</li>`; return; }
  const list = await r.json();
  $("profiles").innerHTML = list.map((p) => `
    <li class="card" style="--c:var(--line)">
      <strong>${esc(p.name)}</strong> ${p.party ? `<span class="muted">${esc(p.party)}</span>` : ""}
      <div class="score">${p.reliability_score ?? "—"}<span class="muted"> / 100</span></div>
      <div class="muted">${p.n_claims} affirmation(s) · ${p.n_speeches} discours</div>
      <div>${Object.entries(p.verdicts).map(([v, n]) => `<span class="badge" style="--c:var(--${v})">${LABELS[v]} · ${n}</span>`).join(" ")}</div>
    </li>`).join("") || `<li class="muted">Aucune donnée pour l'instant.</li>`;
}
