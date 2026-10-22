"""Lot D — Stockage SQLite + agrégats par personnalité politique.

Fichier : backend/factcheck.db (ignoré par git). Schéma : db/schema.sql.
Pour passer sur Supabase/Postgres : garder les mêmes fonctions, changer `connect()`.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from .models import ClaimResult, ExtractedClaim, PoliticianProfile, Speaker, Speech, Verification

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("DB_PATH", ROOT / "backend" / "factcheck.db"))

# Poids des verdicts pour le score de fiabilité (0-100). Voir docs/METHODOLOGIE.md.
VERDICT_WEIGHTS = {"vrai": 1.0, "plutot_vrai": 0.75, "imprecis": 0.5, "trompeur": 0.25, "faux": 0.0}
MIN_CLAIMS_FOR_SCORE = 5


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with connect() as c:
        c.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))


def save_speech(speech: Speech, transcript_json: str | None) -> None:
    pid = slug(speech.speaker.name)
    with connect() as c:
        c.execute("INSERT INTO politicians(id, name, party) VALUES (?,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET party=COALESCE(excluded.party, party)",
                  (pid, speech.speaker.name, speech.speaker.party))
        c.execute("DELETE FROM speeches WHERE id=?", (speech.id,))  # ré-analyse = on remplace
        c.execute("INSERT INTO speeches(id, politician_id, video_id, url, title, date, transcript) VALUES (?,?,?,?,?,?,?)",
                  (speech.id, pid, speech.video_id, speech.url, speech.title, speech.date, transcript_json))


def save_result(r: ClaimResult, speaker: Speaker) -> None:
    cl, v = r.claim, r.verification
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (r.id, r.speech_id, slug(speaker.name), cl.quote, cl.claim, cl.timestamp_start,
                   cl.category.value, cl.claim_type.value, cl.indicator, cl.value,
                   cl.unit.value if cl.unit else None, cl.period_start, cl.period_end, cl.model_dump_json()))
        c.execute("INSERT OR REPLACE INTO verifications(claim_id, verdict, method, official_value, official_period, confidence, data) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (r.id, v.verdict.value, v.method.value, v.official_value, v.official_period, v.confidence, v.model_dump_json()))


def get_speech(speech_id: str) -> tuple[Speech, list[ClaimResult]] | None:
    with connect() as c:
        s = c.execute("SELECT s.*, p.name, p.party FROM speeches s JOIN politicians p ON p.id=s.politician_id WHERE s.id=?",
                      (speech_id,)).fetchone()
        if s is None:
            return None
        rows = c.execute("SELECT c.id, c.speech_id, c.data AS cdata, v.data AS vdata FROM claims c "
                         "JOIN verifications v ON v.claim_id=c.id WHERE c.speech_id=? ORDER BY c.timestamp_start",
                         (speech_id,)).fetchall()
    speech = Speech(id=s["id"], video_id=s["video_id"], url=s["url"], title=s["title"], date=s["date"],
                    speaker=Speaker(name=s["name"], party=s["party"]))
    results = [ClaimResult(id=r["id"], speech_id=r["speech_id"],
                           claim=ExtractedClaim.model_validate_json(r["cdata"]),
                           verification=Verification.model_validate_json(r["vdata"])) for r in rows]
    return speech, results


def list_politicians() -> list[PoliticianProfile]:
    with connect() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM politicians ORDER BY name")]
    return [p for p in (profile(i) for i in ids) if p]


def profile(pid: str) -> PoliticianProfile | None:
    with connect() as c:
        p = c.execute("SELECT * FROM politicians WHERE id=?", (pid,)).fetchone()
        if p is None:
            return None
        n_speeches = c.execute("SELECT COUNT(*) FROM speeches WHERE politician_id=?", (pid,)).fetchone()[0]
        rows = c.execute("SELECT c.category, v.verdict FROM claims c JOIN verifications v ON v.claim_id=c.id "
                         "WHERE c.politician_id=?", (pid,)).fetchall()
    verdicts: dict[str, int] = {}
    by_cat: dict[str, dict[str, int]] = {}
    for r in rows:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        cat = by_cat.setdefault(r["category"], {})
        cat[r["verdict"]] = cat.get(r["verdict"], 0) + 1
    scored = [VERDICT_WEIGHTS[r["verdict"]] for r in rows if r["verdict"] in VERDICT_WEIGHTS]
    score = round(100 * sum(scored) / len(scored), 1) if len(scored) >= MIN_CLAIMS_FOR_SCORE else None
    return PoliticianProfile(id=pid, name=p["name"], party=p["party"], n_speeches=n_speeches, n_claims=len(rows),
                             verdicts=verdicts, reliability_score=score, by_category=by_cat)


def dump_transcript(segments) -> str:
    return json.dumps([s.model_dump() for s in segments], ensure_ascii=False)
