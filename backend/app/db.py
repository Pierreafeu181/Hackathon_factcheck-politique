"""Lot D — Stockage + agrégats par personnalité politique.

Deux moteurs, même schéma (db/schema.sql) et mêmes requêtes :
- SQLite par défaut : backend/factcheck.db (ignoré par git), chemin modifiable via DB_PATH ;
- PostgreSQL (Aiven, Supabase…) si DATABASE_URL est défini dans backend/.env.
Les requêtes sont écrites avec des `?` ; `_Conn` les traduit en `%s` pour psycopg.
"""
from __future__ import annotations

import atexit
import json
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

from .models import ClaimResult, ExtractedClaim, PoliticianProfile, Speaker, Speech, Verification

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")  # db est importé avant llm, qui charge aussi ce fichier
DB_PATH = Path(os.getenv("DB_PATH", ROOT / "backend" / "factcheck.db"))
DATABASE_URL = os.getenv("DATABASE_URL", "")  # vide = SQLite

# Poids des verdicts pour le score de fiabilité (0-100). Voir docs/METHODOLOGIE.md.
VERDICT_WEIGHTS = {"vrai": 1.0, "plutot_vrai": 0.75, "imprecis": 0.5, "trompeur": 0.25, "faux": 0.0}
MIN_CLAIMS_FOR_SCORE = 5


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class _Conn:
    """Connexion psycopg qui accepte les `?` de SQLite et renvoie des lignes indexées par nom."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params: tuple = ()):
        return self._conn.execute(sql.replace("?", "%s"), params)


_pool = None


def _pg_pool():
    global _pool
    if _pool is None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, kwargs={"row_factory": dict_row}, open=True)
        atexit.register(_pool.close)
    return _pool


@contextmanager
def connect():
    if DATABASE_URL:
        with _pg_pool().connection() as conn:  # commit en sortie, rollback si exception
            yield _Conn(conn)
        return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    with connect() as c:
        if DATABASE_URL:
            c._conn.execute(schema)  # sans paramètres, psycopg accepte plusieurs instructions
        else:
            c.executescript(schema)


def save_speech(speech: Speech, transcript_json: str | None) -> None:
    pid = slug(speech.speaker.name)
    with connect() as c:
        c.execute("INSERT INTO politicians(id, name, party) VALUES (?,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET party=COALESCE(excluded.party, politicians.party)",
                  (pid, speech.speaker.name, speech.speaker.party))
        c.execute("DELETE FROM speeches WHERE id=?", (speech.id,))  # ré-analyse = on remplace
        c.execute("INSERT INTO speeches(id, politician_id, video_id, url, title, date, transcript) VALUES (?,?,?,?,?,?,?)",
                  (speech.id, pid, speech.video_id, speech.url, speech.title, speech.date, transcript_json))


def save_result(r: ClaimResult, speaker: Speaker) -> None:
    cl, v = r.claim, r.verification
    with connect() as c:
        c.execute("INSERT INTO claims(id, speech_id, politician_id, quote, claim, timestamp_start, category, claim_type, "
                  "indicator, value, unit, period_start, period_end, data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET speech_id=excluded.speech_id, politician_id=excluded.politician_id, "
                  "quote=excluded.quote, claim=excluded.claim, timestamp_start=excluded.timestamp_start, "
                  "category=excluded.category, claim_type=excluded.claim_type, indicator=excluded.indicator, "
                  "value=excluded.value, unit=excluded.unit, period_start=excluded.period_start, "
                  "period_end=excluded.period_end, data=excluded.data",
                  (r.id, r.speech_id, slug(speaker.name), cl.quote, cl.claim, cl.timestamp_start,
                   cl.category.value, cl.claim_type.value, cl.indicator, cl.value,
                   cl.unit.value if cl.unit else None, cl.period_start, cl.period_end, cl.model_dump_json()))
        c.execute("INSERT INTO verifications(claim_id, verdict, method, official_value, official_period, confidence, data) "
                  "VALUES (?,?,?,?,?,?,?) ON CONFLICT(claim_id) DO UPDATE SET verdict=excluded.verdict, "
                  "method=excluded.method, official_value=excluded.official_value, "
                  "official_period=excluded.official_period, confidence=excluded.confidence, data=excluded.data, "
                  "checked_at=CURRENT_TIMESTAMP",
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
        n_speeches = c.execute("SELECT COUNT(*) AS n FROM speeches WHERE politician_id=?", (pid,)).fetchone()["n"]
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


def claims_for(pid: str, limit: int = 50) -> list[dict]:
    """Dernières affirmations vérifiées d'une personnalité, pour l'onglet Profils de l'extension."""
    with connect() as c:
        rows = c.execute(
            "SELECT c.quote, c.timestamp_start, c.category, s.title, s.url, s.date, s.analyzed_at, v.verdict, v.data AS vdata "
            "FROM claims c JOIN speeches s ON s.id = c.speech_id JOIN verifications v ON v.claim_id = c.id "
            "WHERE c.politician_id = ? ORDER BY s.analyzed_at DESC, c.timestamp_start LIMIT ?", (pid, limit)).fetchall()
    out = []
    for r in rows:
        v = Verification.model_validate_json(r["vdata"])
        out.append({"quote": r["quote"], "verdict": r["verdict"], "category": r["category"], "explanation": v.explanation,
                    "correction": v.correction, "sources": [{"title": f"{s.publisher} – {s.title}", "url": s.url} for s in v.sources],
                    "start": r["timestamp_start"], "title": r["title"], "url": r["url"], "date": r["date"] or str(r["analyzed_at"])[:10]})
    return out
