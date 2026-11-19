CREATE TABLE IF NOT EXISTS presence_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pepper TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS presence_session (
    token_hash TEXT PRIMARY KEY,
    member TEXT NOT NULL,
    label TEXT NOT NULL,
    expires INTEGER NOT NULL,
    visible_until INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS presence_expiry ON presence_session(expires);
CREATE INDEX IF NOT EXISTS presence_visible ON presence_session(visible_until);
