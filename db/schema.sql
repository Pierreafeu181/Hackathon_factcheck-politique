-- Schéma de stockage. SQLite pour le hackathon ; compatible Postgres/Supabase
-- (remplacer TEXT JSON par JSONB, REAL par DOUBLE PRECISION si besoin).

CREATE TABLE IF NOT EXISTS politicians (
    id          TEXT PRIMARY KEY,          -- slug : "prenom-nom"
    name        TEXT NOT NULL,
    party       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS speeches (
    id            TEXT PRIMARY KEY,        -- "yt:<video_id>" ou uuid
    politician_id TEXT NOT NULL REFERENCES politicians(id),
    video_id      TEXT,
    url           TEXT,
    title         TEXT,
    date          TEXT,                    -- AAAA-MM-JJ
    transcript    TEXT,                    -- JSON [{start,duration,text}]
    analyzed_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS claims (
    id              TEXT PRIMARY KEY,
    speech_id       TEXT NOT NULL REFERENCES speeches(id) ON DELETE CASCADE,
    politician_id   TEXT NOT NULL REFERENCES politicians(id),
    quote           TEXT NOT NULL,
    claim           TEXT NOT NULL,
    timestamp_start REAL,
    category        TEXT NOT NULL,
    claim_type      TEXT NOT NULL,
    indicator       TEXT,
    value           REAL,
    unit            TEXT,
    period_start    TEXT,
    period_end      TEXT,
    data            TEXT NOT NULL           -- JSON ExtractedClaim complet
);

CREATE TABLE IF NOT EXISTS verifications (
    claim_id        TEXT PRIMARY KEY REFERENCES claims(id) ON DELETE CASCADE,
    verdict         TEXT NOT NULL,
    method          TEXT NOT NULL,
    official_value  REAL,
    official_period TEXT,
    confidence      REAL,
    data            TEXT NOT NULL,          -- JSON Verification complet (explication, sources…)
    checked_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_claims_politician ON claims(politician_id);
CREATE INDEX IF NOT EXISTS idx_claims_indicator  ON claims(indicator);
CREATE INDEX IF NOT EXISTS idx_speeches_video    ON speeches(video_id);
