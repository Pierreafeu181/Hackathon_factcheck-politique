// Script injecté dans youtube.com. Répond aux messages du panneau latéral.
//   getVideoInfo        → { videoId, title, channel, currentTime }
//   seek {t}            → place la vidéo à t secondes et lance la lecture
//   getDomTranscript    → segments du panneau « Transcription » de YouTube s'il est ouvert (plan B
//                         quand le backend ne peut pas récupérer le transcript)

function videoId() {
  const u = new URL(location.href);
  if (u.pathname === "/watch") return u.searchParams.get("v");
  const m = u.pathname.match(/^\/(?:live|shorts|embed)\/([\w-]{11})/);
  return m ? m[1] : null;
}

function parseTimestamp(txt) {
  // "1:02:03" ou "12:34" → secondes
  return txt.trim().split(":").map(Number).reduce((acc, n) => acc * 60 + n, 0);
}

function domTranscript() {
  const rows = document.querySelectorAll("ytd-transcript-segment-renderer");
  return Array.from(rows).map((row) => ({
    start: parseTimestamp(row.querySelector(".segment-timestamp")?.textContent || "0"),
    duration: 0,
    text: (row.querySelector(".segment-text")?.textContent || "").trim(),
  })).filter((s) => s.text);
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  const video = document.querySelector("video");
  if (msg.type === "getVideoInfo") {
    sendResponse({
      videoId: videoId(),
      title: document.querySelector("h1.ytd-watch-metadata")?.textContent?.trim() || document.title,
      channel: document.querySelector("ytd-channel-name a")?.textContent?.trim() || null,
      currentTime: video ? video.currentTime : 0,
    });
  } else if (msg.type === "seek" && video) {
    video.currentTime = msg.t;
    video.play();
    sendResponse({ ok: true });
  } else if (msg.type === "getDomTranscript") {
    sendResponse({ segments: domTranscript() });
  }
  return true;
});
