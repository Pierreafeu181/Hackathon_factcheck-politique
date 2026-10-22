-- Schéma de stockage, commun à SQLite (défaut) et PostgreSQL (DATABASE_URL, ex. Aiven).
-- N'utiliser que du SQL accepté par les deux : CURRENT_TIMESTAMP, DOUBLE PRECISION, ON CONFLICT…
-- Les colonnes JSON restent en TEXT pour rester portables.

CREATE TABLE IF NOT EXISTS politicians (
    id          TEXT PRIMARY KEY,          -- slug : "prenom-nom"
    name        TEXT NOT NULL,
    party       TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS speeches (
    id            TEXT PRIMARY KEY,        -- "yt:<video_id>" ou uuid
    politician_id TEXT NOT NULL REFERENCES politicians(id),
    video_id      TEXT,
    url           TEXT,
    title         TEXT,
    date          TEXT,                    -- AAAA-MM-JJ
    transcript    TEXT,                    -- JSON [{start,duration,text}]
    analyzed_at   TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS claims (
    id              TEXT PRIMARY KEY,
    speech_id       TEXT NOT NULL REFERENCES speeches(id) ON DELETE CASCADE,
    politician_id   TEXT NOT NULL REFERENCES politicians(id),
    quote           TEXT NOT NULL,
    claim           TEXT NOT NULL,
    timestamp_start DOUBLE PRECISION,
    category        TEXT NOT NULL,
    claim_type      TEXT NOT NULL,
    indicator       TEXT,
    value           DOUBLE PRECISION,
    unit            TEXT,
    period_start    TEXT,
    period_end      TEXT,
    data            TEXT NOT NULL           -- JSON ExtractedClaim complet
);

CREATE TABLE IF NOT EXISTS verifications (
    claim_id        TEXT PRIMARY KEY REFERENCES claims(id) ON DELETE CASCADE,
    verdict         TEXT NOT NULL,
    method          TEXT NOT NULL,
    official_value  DOUBLE PRECISION,
    official_period TEXT,
    confidence      DOUBLE PRECISION,
    data            TEXT NOT NULL,          -- JSON Verification complet (explication, sources…)
    checked_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_claims_politician ON claims(politician_id);
CREATE INDEX IF NOT EXISTS idx_claims_indicator  ON claims(indicator);
CREATE INDEX IF NOT EXISTS idx_speeches_video    ON speeches(video_id);
