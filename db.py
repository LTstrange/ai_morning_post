import hashlib
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data.db"


def get_connection(db_path=DB_PATH):
    """获取数据库连接，开启外键约束。"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path=DB_PATH):
    """初始化数据库，创建所有表。"""
    conn = get_connection(db_path)
    conn.executescript("""
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
    """)
    conn.commit()
    conn.close()


def ensure_feed(conn, name, url):
    """确保 feeds 表中存在该源，返回 feed_id。"""
    row = conn.execute(
        "SELECT id FROM feeds WHERE url = ?", (url,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO feeds (name, url) VALUES (?, ?)", (name, url)
    )
    conn.commit()
    return cur.lastrowid


def save_raw_feed(conn, feed_id, raw_content):
    """保存原始 RSS 内容，内容相同则跳过。返回是否实际插入。"""
    content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
    exists = conn.execute(
        "SELECT 1 FROM raw_feeds WHERE feed_id = ? AND content_hash = ? LIMIT 1",
        (feed_id, content_hash),
    ).fetchone()
    if exists:
        return False
    conn.execute(
        "INSERT INTO raw_feeds (feed_id, raw_content, content_hash) VALUES (?, ?, ?)",
        (feed_id, raw_content, content_hash),
    )
    conn.commit()
    return True


def save_article(conn, feed_id, article):
    """保存解析后的文章，link 相同则跳过。返回是否实际插入。"""
    exists = conn.execute(
        "SELECT 1 FROM articles WHERE link = ? LIMIT 1",
        (article["link"],),
    ).fetchone()
    if exists:
        return False
    conn.execute(
        "INSERT INTO articles (feed_id, link, title, summary, published, authors) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            feed_id,
            article["link"],
            article["title"],
            article["summary"],
            article["published"],
            json.dumps(article["authors"], ensure_ascii=False),
        ),
    )
    conn.commit()
    return True


def ensure_user(conn, name):
    """确保 users 表中存在该用户，返回 user_id。"""
    row = conn.execute(
        "SELECT id FROM users WHERE name = ?", (name,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO users (name) VALUES (?)", (name,)
    )
    conn.commit()
    return cur.lastrowid


def ensure_subscription(conn, user_id, feed_id):
    """确保订阅关系存在，已存在则跳过。"""
    exists = conn.execute(
        "SELECT 1 FROM subscriptions WHERE user_id = ? AND feed_id = ? LIMIT 1",
        (user_id, feed_id),
    ).fetchone()
    if exists:
        return False
    conn.execute(
        "INSERT INTO subscriptions (user_id, feed_id) VALUES (?, ?)",
        (user_id, feed_id),
    )
    conn.commit()
    return True


def fetch_user_latest_articles(conn, user_id, limit=5):
    """根据用户订阅，按 published 降序取最近的 limit 篇论文。返回 (latest_date, rows)。"""
    rows = conn.execute(
        "SELECT a.title, a.authors, a.link, a.summary, a.published, f.name AS feed_name "
        "FROM articles a "
        "JOIN feeds f ON a.feed_id = f.id "
        "JOIN subscriptions s ON s.feed_id = f.id "
        "WHERE s.user_id = ? "
        "ORDER BY a.published DESC "
        "LIMIT ?",
        (user_id, limit),
    ).fetchall()

    if not rows:
        return None, []

    latest_date = rows[0]["published"][:10]
    return latest_date, rows
