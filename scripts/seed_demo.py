"""Pré-analyse des vidéos de démo (data/fixtures/demo_videos.json) sur le serveur hébergé.

Les sous-titres sont lus depuis CE Mac avec yt-dlp (YouTube bloque les serveurs, pas les particuliers),
puis envoyés au serveur comme le ferait l'extension, avec le nom de l'orateur. Résultat : verdicts en
cache sur le serveur (affichage instantané pendant la démo) et profils remplis dans Aiven.

    python3 scripts/seed_demo.py --server https://…aiven.app            # clé lue dans .context/api_token.txt
    API_TOKEN=… python3 scripts/seed_demo.py --server http://localhost:8790

À relancer après un redéploiement : le cache du serveur repart de zéro (les profils, eux, restent dans Aiven).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def captions(video_id: str) -> tuple[str, list[dict]]:
    """Titre et sous-titres (langue d'origine : manuels si présents, sinon automatiques), regroupés en blocs."""
    with tempfile.TemporaryDirectory() as tmp:
        out = subprocess.run(
            ["yt-dlp", "--ignore-config", "--skip-download", "--write-subs", "--write-auto-subs",
             "--sub-langs", "fr,fr-orig,fr-FR", "--sub-format", "json3", "--print", "%(title)s",
             "--no-simulate", "-o", f"{tmp}/%(id)s.%(ext)s", f"https://www.youtube.com/watch?v={video_id}"],
            capture_output=True, text=True, timeout=180)
        title = (out.stdout.strip().splitlines() or [video_id])[0]
        files = sorted(glob.glob(f"{tmp}/*.json3"), key=lambda f: ("orig" in f, f))  # manuels d'abord
        if not files:
            raise RuntimeError(f"pas de sous-titres français ({out.stderr.strip()[-200:]})")
        events = json.load(open(files[0], encoding="utf-8")).get("events", [])
    lines = [{"start": round(e.get("tStartMs", 0) / 1000, 1),
              "text": " ".join("".join(s.get("utf8", "") for s in e["segs"]).split())}
             for e in events if e.get("segs")]
    segments, total = [], 0
    for line in (l for l in lines if l["text"]):
        total += len(line["text"])
        if total > 30_000:
            break
        if segments and len(segments[-1]["text"]) < 400:
            segments[-1]["text"] += " " + line["text"]
        else:
            segments.append(dict(line))
    return title, segments


def post(server: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(f"{server}/api/check?force=1", data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "Origin": "chrome-extension://seed-demo", **({"X-VerifPol-Token": token} if token else {})})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    args = ap.parse_args()
    token = os.getenv("API_TOKEN") or (ROOT / ".context" / "api_token.txt").read_text().strip()
    for v in json.loads((ROOT / "data" / "fixtures" / "demo_videos.json").read_text(encoding="utf-8")):
        t0 = time.time()
        try:
            title, segments = captions(v["video_id"])
            res = post(args.server.rstrip("/"), token, {
                "source": {"kind": "youtube", "url": f"https://www.youtube.com/watch?v={v['video_id']}", "title": title},
                "segments": segments, "politician": {"name": v["speaker"], "party": v.get("party")},
                "date": v.get("date") or dt.date.today().isoformat()})
            verdicts = [c["verdict"] for c in res.get("claims", [])]
            print(f"✅ {v['speaker']} — {title[:60]} : {len(verdicts)} affirmations {verdicts} ({time.time() - t0:.0f} s)")
        except Exception as e:  # noqa: BLE001 — on continue avec les autres vidéos
            print(f"❌ {v['speaker']} ({v['video_id']}) : {e}")


if __name__ == "__main__":
    main()
