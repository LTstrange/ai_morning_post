CREATE TABLE IF NOT EXISTS feeds (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    url        TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS raw_feeds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id      INTEGER NOT NULL REFERENCES feeds(id),
    raw_content  TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_raw_feeds_dedup
    ON raw_feeds(feed_id, content_hash);

CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    feed_id    INTEGER NOT NULL REFERENCES feeds(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, feed_id)
);

CREATE TABLE IF NOT EXISTS articles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id    INTEGER NOT NULL REFERENCES feeds(id),
    link       TEXT NOT NULL UNIQUE,
    title      TEXT NOT NULL,
    summary    TEXT,
    published  TEXT,
    authors    TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS push_batches (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    report         TEXT,
    voice_script   TEXT,
    tts_audio_path TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_article_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    article_id INTEGER NOT NULL REFERENCES articles(id),
    batch_id   INTEGER NOT NULL REFERENCES push_batches(id) ON DELETE CASCADE,
    UNIQUE(user_id, article_id)
);

CREATE INDEX IF NOT EXISTS idx_history_batch
    ON user_article_history(batch_id);
