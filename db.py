import hashlib
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data.db"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_connection(db_path=DB_PATH):
    """获取数据库连接，开启外键约束。"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path=DB_PATH):
    """初始化数据库，运行所有未应用的迁移。"""
    conn = get_connection(db_path)
    migrate(conn)
    conn.close()


def migrate(conn):
    """执行所有未应用的数据库迁移。"""
    # 确保迁移版本表存在
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version     INTEGER PRIMARY KEY,"
        "  applied_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    conn.commit()

    # 检测当前版本
    current = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current_version = current[0] if current[0] is not None else 0

    # 存量数据库兼容：feeds 表已存在但 schema_version 为空 → 标记版本 1
    feeds_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='feeds'"
    ).fetchone()
    if feeds_exists and current_version == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        conn.commit()
        current_version = 1

    # 扫描迁移文件并按版本号排序执行
    if not MIGRATIONS_DIR.exists():
        return

    migration_files = sorted(
        f
        for f in MIGRATIONS_DIR.iterdir()
        if f.suffix == ".sql" and f.name[0].isdigit()
    )

    for mf in migration_files:
        version = int(mf.name.split("_")[0])
        if version > current_version:
            sql = mf.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            conn.commit()
            print(f"  [迁移] 已应用版本 {version}: {mf.name}")


def ensure_feed(conn, name, url, publisher=None):
    """确保 feeds 表中存在该源，返回 feed_id。若已存在则更新 publisher。"""
    row = conn.execute("SELECT id FROM feeds WHERE url = ?", (url,)).fetchone()
    if row:
        if publisher:
            conn.execute(
                "UPDATE feeds SET publisher = ? WHERE id = ?",
                (publisher, row["id"]),
            )
            conn.commit()
        return row["id"]
    cur = conn.execute(
        "INSERT INTO feeds (name, url, publisher) VALUES (?, ?, ?)",
        (name, url, publisher),
    )
    conn.commit()
    return cur.lastrowid


def get_latest_raw_feed(conn, feed_id):
    """获取该 feed 最近一次拉取的时间，不存在则返回 None。"""
    row = conn.execute(
        "SELECT fetched_at FROM raw_feeds WHERE feed_id = ? ORDER BY fetched_at DESC LIMIT 1",
        (feed_id,),
    ).fetchone()
    return row["fetched_at"] if row else None


def save_raw_feed(conn, feed_id, raw_content):
    """保存原始 RSS 内容，内容相同则跳过。返回是否实际插入。"""
    content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
    exists = conn.execute(
        "SELECT 1 FROM raw_feeds WHERE feed_id = ? AND content_hash = ? LIMIT 1",
        (feed_id, content_hash),
    ).fetchone()
    if exists:
        conn.execute(
            "UPDATE raw_feeds SET fetched_at = CURRENT_TIMESTAMP "
            "WHERE feed_id = ? AND content_hash = ?",
            (feed_id, content_hash),
        )
        conn.commit()
        return False
    conn.execute(
        "INSERT INTO raw_feeds (feed_id, raw_content, content_hash) VALUES (?, ?, ?)",
        (feed_id, raw_content, content_hash),
    )
    conn.commit()
    return True


def article_exists(conn, link):
    """检查文章是否已存在（按 link 去重）。"""
    return (
        conn.execute(
            "SELECT 1 FROM articles WHERE link = ? LIMIT 1", (link,)
        ).fetchone()
        is not None
    )


def save_article(conn, feed_id, article, embedding=None):
    """保存解析后的文章，link 相同则跳过。返回是否实际插入。"""
    if article_exists(conn, article["link"]):
        return False
    conn.execute(
        "INSERT INTO articles (feed_id, link, title, summary, published, authors, doi, embedding) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            feed_id,
            article["link"],
            article["title"],
            article["summary"],
            article["published"],
            json.dumps(article["authors"], ensure_ascii=False),
            article.get("doi", ""),
            embedding,
        ),
    )
    conn.commit()
    return True


def ensure_user(conn, name, email=None):
    """确保 users 表中存在该用户，返回 user_id。若提供 email 则更新。"""
    row = conn.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
    if row:
        if email is not None:
            conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, row["id"]))
            conn.commit()
        return row["id"]
    cur = conn.execute("INSERT INTO users (name, email) VALUES (?, ?)", (name, email))
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
    """根据用户订阅，按 published 降序取最近的 limit 篇论文。返回 rows。"""
    rows = conn.execute(
        "SELECT a.id, a.title, a.authors, a.link, a.summary, a.published, f.name AS feed_name "
        "FROM articles a "
        "JOIN feeds f ON a.feed_id = f.id "
        "JOIN subscriptions s ON s.feed_id = f.id "
        "WHERE s.user_id = ? "
        "ORDER BY a.published DESC "
        "LIMIT ?",
        (user_id, limit),
    ).fetchall()

    return rows


def create_push_batch(conn, user_id):
    """创建推送批次，返回 batch_id。"""
    cur = conn.execute(
        "INSERT INTO push_batches (user_id) VALUES (?)",
        (user_id,),
    )
    conn.commit()
    return cur.lastrowid


def mark_article_pushed(conn, user_id, article_id, batch_id):
    """标记文章已推送给用户，关联到指定批次。"""
    try:
        conn.execute(
            "INSERT INTO user_article_history (user_id, article_id, batch_id) VALUES (?, ?, ?)",
            (user_id, article_id, batch_id),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_today_articles(conn, user_id, today):
    """获取用户订阅期刊中当天发布的文章。"""
    rows = conn.execute(
        "SELECT a.id, a.title, a.authors, a.link, a.summary, a.published, a.embedding, f.name AS feed_name "
        "FROM articles a "
        "JOIN feeds f ON a.feed_id = f.id "
        "JOIN subscriptions s ON s.feed_id = f.id "
        "WHERE s.user_id = ? AND substr(a.published, 1, 10) = ? AND a.summary IS NOT NULL "
        "ORDER BY a.published DESC",
        (user_id, today),
    ).fetchall()
    return rows


def get_unpushed_subscribed_articles(conn, user_id, exclude_ids, limit):
    """从用户订阅期刊中随机取未推送过的文章，排除指定 ID。"""
    if not exclude_ids:
        exclude_clause = ""
        params = (user_id, user_id, limit)
    else:
        placeholders = ",".join("?" * len(exclude_ids))
        exclude_clause = f"AND a.id NOT IN ({placeholders})"
        params = (user_id, *exclude_ids, user_id, limit)

    rows = conn.execute(
        f"SELECT a.id, a.title, a.authors, a.link, a.summary, a.published, a.embedding, f.name AS feed_name "
        f"FROM articles a "
        f"JOIN feeds f ON a.feed_id = f.id "
        f"JOIN subscriptions s ON s.feed_id = f.id "
        f"WHERE s.user_id = ? {exclude_clause} "
        f"AND a.summary IS NOT NULL "
        f"AND a.id NOT IN (SELECT article_id FROM user_article_history WHERE user_id = ?) "
        f"ORDER BY RANDOM() "
        f"LIMIT ?",
        params,
    ).fetchall()
    return rows


def get_unpushed_all_articles(conn, user_id, exclude_ids, limit):
    """从所有期刊中随机取未推送过的文章，排除指定 ID。"""
    if not exclude_ids:
        exclude_clause = ""
        params = (user_id, limit)
    else:
        placeholders = ",".join("?" * len(exclude_ids))
        exclude_clause = f"AND a.id NOT IN ({placeholders})"
        params = (*exclude_ids, user_id, limit)

    rows = conn.execute(
        f"SELECT a.id, a.title, a.authors, a.link, a.summary, a.published, a.embedding, f.name AS feed_name "
        f"FROM articles a "
        f"JOIN feeds f ON a.feed_id = f.id "
        f"WHERE a.summary IS NOT NULL {exclude_clause} "
        f"AND a.id NOT IN (SELECT article_id FROM user_article_history WHERE user_id = ?) "
        f"ORDER BY RANDOM() "
        f"LIMIT ?",
        params,
    ).fetchall()
    return rows


def reset_user_history(
    conn, user_id=None, batch_id=None, date_str=None, after_date=None
):
    """重置用户推送历史。通过删除 push_batches 级联清理 history。

    - user_id: 限定用户
    - batch_id: 删除指定批次
    - date_str: 删除指定日期的批次（YYYY-MM-DD）
    - after_date: 删除该日期之后的批次（YYYY-MM-DD）
    """
    if batch_id:
        conn.execute("DELETE FROM push_batches WHERE id = ?", (batch_id,))
    elif date_str:
        if user_id:
            conn.execute(
                "DELETE FROM push_batches WHERE user_id = ? AND DATE(created_at) = ?",
                (user_id, date_str),
            )
        else:
            conn.execute(
                "DELETE FROM push_batches WHERE DATE(created_at) = ?",
                (date_str,),
            )
    elif after_date:
        if user_id:
            conn.execute(
                "DELETE FROM push_batches WHERE user_id = ? AND DATE(created_at) > ?",
                (user_id, after_date),
            )
        else:
            conn.execute(
                "DELETE FROM push_batches WHERE DATE(created_at) > ?",
                (after_date,),
            )
    elif user_id:
        conn.execute("DELETE FROM push_batches WHERE user_id = ?", (user_id,))
    else:
        conn.execute("DELETE FROM push_batches")
    conn.commit()


def get_user_history(
    conn,
    user_id=None,
    batch_id=None,
    date_str=None,
    date_from=None,
    date_to=None,
    limit=None,
):
    """获取用户推送历史。

    - user_id: 限定用户
    - batch_id: 限定批次
    - date_str: 限定日期（YYYY-MM-DD）
    - date_from / date_to: 日期范围
    - limit: 最大返回条数（None 表示不限）
    """
    base = (
        "SELECT u.name AS user_name, a.title, b.created_at AS pushed_at, b.id AS batch_id "
        "FROM user_article_history h "
        "JOIN push_batches b ON h.batch_id = b.id "
        "JOIN users u ON h.user_id = u.id "
        "JOIN articles a ON h.article_id = a.id "
    )
    conditions = []
    params = []

    if user_id:
        conditions.append("h.user_id = ?")
        params.append(user_id)
    if batch_id:
        conditions.append("b.id = ?")
        params.append(batch_id)
    if date_str:
        conditions.append("DATE(b.created_at) = ?")
        params.append(date_str)
    if date_from:
        conditions.append("DATE(b.created_at) >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("DATE(b.created_at) <= ?")
        params.append(date_to)

    if conditions:
        base += "WHERE " + " AND ".join(conditions) + " "

    base += "ORDER BY b.created_at DESC, u.name"

    if limit:
        base += " LIMIT ?"
        params.append(limit)

    return conn.execute(base, params).fetchall()


def get_push_batches(conn, user_id=None):
    """获取推送批次列表及每批次文章数。"""
    base = (
        "SELECT b.id, u.name AS user_name, b.created_at, COUNT(h.id) AS article_count, "
        "b.report IS NOT NULL AS has_report, "
        "b.voice_script IS NOT NULL AS has_voice, "
        "b.tts_audio_path IS NOT NULL AS has_tts "
        "FROM push_batches b "
        "JOIN users u ON b.user_id = u.id "
        "LEFT JOIN user_article_history h ON h.batch_id = b.id "
    )
    params = []
    if user_id:
        base += "WHERE b.user_id = ? "
        params.append(user_id)
    base += "GROUP BY b.id ORDER BY b.created_at DESC"
    return conn.execute(base, params).fetchall()


def get_batch(conn, batch_id):
    """获取批次信息，包括生成产物。不存在返回 None。"""
    return conn.execute(
        "SELECT b.*, u.name AS user_name "
        "FROM push_batches b "
        "JOIN users u ON b.user_id = u.id "
        "WHERE b.id = ?",
        (batch_id,),
    ).fetchone()


def get_batch_articles(conn, batch_id):
    """根据 batch_id 查出关联的文章列表。"""
    return conn.execute(
        "SELECT a.id, a.title, a.authors, a.link, a.summary, a.published, f.name AS feed_name "
        "FROM user_article_history h "
        "JOIN articles a ON h.article_id = a.id "
        "JOIN feeds f ON a.feed_id = f.id "
        "WHERE h.batch_id = ? "
        "ORDER BY a.published DESC",
        (batch_id,),
    ).fetchall()


def update_batch_report(conn, batch_id, report):
    """更新早报，级联清空下游（voice_script + tts_audio_path）。"""
    row = conn.execute(
        "SELECT tts_audio_path FROM push_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    if row and row["tts_audio_path"]:
        audio = Path(row["tts_audio_path"])
        if audio.exists():
            audio.unlink()
    conn.execute(
        "UPDATE push_batches SET report = ?, voice_script = NULL, tts_audio_path = NULL WHERE id = ?",
        (report, batch_id),
    )
    conn.commit()


def update_batch_voice(conn, batch_id, voice_script):
    """更新语音稿，级联清空下游（tts_audio_path）。"""
    row = conn.execute(
        "SELECT tts_audio_path FROM push_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    if row and row["tts_audio_path"]:
        audio = Path(row["tts_audio_path"])
        if audio.exists():
            audio.unlink()
    conn.execute(
        "UPDATE push_batches SET voice_script = ?, tts_audio_path = NULL WHERE id = ?",
        (voice_script, batch_id),
    )
    conn.commit()


def update_batch_tts(conn, batch_id, tts_audio_path):
    """更新 TTS 音频路径。"""
    conn.execute(
        "UPDATE push_batches SET tts_audio_path = ? WHERE id = ?",
        (str(tts_audio_path), batch_id),
    )
    conn.commit()


def add_user(conn, name, email=None):
    """创建新用户。已存在（无论 active 状态）则跳过，返回 None。"""
    exists = conn.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
    if exists:
        return None
    cur = conn.execute("INSERT INTO users (name, email) VALUES (?, ?)", (name, email))
    conn.commit()
    return cur.lastrowid


def get_user(conn, name):
    """按名称查找用户，返回完整 row 或 None。"""
    return conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()


def activate_user(conn, user_id):
    """激活用户（active = 1）。"""
    conn.execute("UPDATE users SET active = 1 WHERE id = ?", (user_id,))
    conn.commit()


def deactivate_user(conn, user_id):
    """停用用户，保留数据和订阅。"""
    conn.execute("UPDATE users SET active = 0 WHERE id = ?", (user_id,))
    conn.commit()


def remove_user(conn, user_id):
    """硬删除用户，级联删除订阅、推送批次、推送历史。"""
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()


def list_users(conn):
    """列出所有用户。"""
    return conn.execute("SELECT * FROM users ORDER BY name").fetchall()


def set_user_subscriptions(conn, user_id, feed_names):
    """原子替换用户的订阅列表。"""
    conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
    for feed_name in feed_names:
        feed = conn.execute(
            "SELECT id FROM feeds WHERE name = ?", (feed_name,)
        ).fetchone()
        if feed:
            conn.execute(
                "INSERT OR IGNORE INTO subscriptions (user_id, feed_id) VALUES (?, ?)",
                (user_id, feed["id"]),
            )
    conn.commit()


def add_subscription(conn, user_id, feed_name):
    """添加单个订阅。返回 feed_id 或 None。"""
    feed = conn.execute("SELECT id FROM feeds WHERE name = ?", (feed_name,)).fetchone()
    if not feed:
        return None
    conn.execute(
        "INSERT OR IGNORE INTO subscriptions (user_id, feed_id) VALUES (?, ?)",
        (user_id, feed["id"]),
    )
    conn.commit()
    return feed["id"]


def remove_subscription(conn, user_id, feed_name):
    """移除单个订阅。返回 feed_id 或 None。"""
    feed = conn.execute("SELECT id FROM feeds WHERE name = ?", (feed_name,)).fetchone()
    if not feed:
        return None
    conn.execute(
        "DELETE FROM subscriptions WHERE user_id = ? AND feed_id = ?",
        (user_id, feed["id"]),
    )
    conn.commit()
    return feed["id"]


def get_user_subscriptions(conn, user_id):
    """获取用户订阅列表。"""
    return conn.execute(
        "SELECT f.name, f.url FROM subscriptions s "
        "JOIN feeds f ON s.feed_id = f.id "
        "WHERE s.user_id = ? ORDER BY f.name",
        (user_id,),
    ).fetchall()


def rename_user(conn, user_id, new_name):
    """重命名用户。"""
    conn.execute("UPDATE users SET name = ? WHERE id = ?", (new_name, user_id))
    conn.commit()


def set_user_interests(conn, user_id, interests):
    """设置用户研究兴趣文本。"""
    conn.execute(
        "UPDATE users SET interests = ? WHERE id = ?",
        (interests, user_id),
    )
    conn.commit()


def set_user_email(conn, user_id, email):
    """设置用户邮箱地址。"""
    conn.execute(
        "UPDATE users SET email = ? WHERE id = ?",
        (email, user_id),
    )
    conn.commit()


def get_unpushed_articles_with_embeddings(conn, user_id, exclude_ids=None):
    """获取所有有 embedding 的未推送文章（含 embedding 字段）。"""
    if not exclude_ids:
        exclude_clause = ""
        params = (user_id,)
    else:
        placeholders = ",".join("?" * len(exclude_ids))
        exclude_clause = f"AND a.id NOT IN ({placeholders})"
        params = (*exclude_ids, user_id)

    rows = conn.execute(
        f"SELECT a.id, a.title, a.authors, a.link, a.summary, a.published, "
        f"a.embedding, f.name AS feed_name "
        f"FROM articles a "
        f"JOIN feeds f ON a.feed_id = f.id "
        f"WHERE a.embedding IS NOT NULL AND a.summary IS NOT NULL {exclude_clause} "
        f"AND a.id NOT IN (SELECT article_id FROM user_article_history WHERE user_id = ?)",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_articles_without_embedding(conn, limit=None):
    """查找缺少 embedding 的文章，返回 id/title/summary。"""
    sql = "SELECT id, title, summary FROM articles WHERE embedding IS NULL"
    params = ()
    if limit:
        sql += " LIMIT ?"
        params = (limit,)
    return conn.execute(sql, params).fetchall()


def update_article_embedding(conn, article_id, embedding_blob):
    """更新单篇文章的 embedding。"""
    conn.execute(
        "UPDATE articles SET embedding = ? WHERE id = ?",
        (embedding_blob, article_id),
    )


def batch_update_embeddings(conn, updates):
    """批量更新文章 embedding。updates: [(embedding_blob, article_id), ...]"""
    conn.executemany(
        "UPDATE articles SET embedding = ? WHERE id = ?",
        updates,
    )
    conn.commit()
