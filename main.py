import json
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import requests

from dotenv import load_dotenv

from db import (
    get_connection, init_db, ensure_feed, save_raw_feed, save_article,
    ensure_user, ensure_subscription, fetch_user_latest_articles,
)
from generate_report import (
    build_user_prompt, generate_report, generate_voice_script, REPORTS_DIR,
)


def load_feeds(path="feeds.json"):
    """读取配置文件，返回 feed 列表。"""
    with open(path) as f:
        return json.load(f)["feeds"]


def _parse_date(raw):
    """将 RFC 2822 日期字符串转为 ISO 8601 格式，解析失败时返回原始字符串。"""
    try:
        return parsedate_to_datetime(raw).isoformat()
    except Exception:
        return raw


def parse_entry(entry):
    """从一条 feedparser entry 中提取字段，返回干净的字典。"""

    # authors 字段是分号分隔的字符串，如 "Alice;Bob;Carol;"
    # 拆成列表，去掉末尾空串
    raw_authors = entry.get("authors", "")
    author_list = [a.strip() for a in raw_authors.split(";") if a.strip()]

    return {
        "title": entry.get("title", ""),
        "link": entry.get("link", ""),
        "summary": entry.get("summary", ""),
        "published": _parse_date(entry.get("published", "")),
        "pub_year": entry.get("pubyear", ""),
        "volume": entry.get("volume", ""),
        "issue": entry.get("issue", ""),
        "start_page": entry.get("startpage", ""),
        "end_page": entry.get("endpage", ""),
        "authors": author_list,
    }


def fetch_and_store_raw_feeds(conn):
    """遍历所有 feed 源，读取本地 XML（无则从 URL 下载），存入 raw_feeds 表。"""
    feeds = load_feeds()
    for feed_cfg in feeds:
        name = feed_cfg["name"]
        url = feed_cfg["url"]

        feed_id = ensure_feed(conn, name, url)

        toc_file = Path("output") / Path(url).stem.upper()
        toc_file = toc_file.with_suffix(".xml")

        if toc_file.exists():
            raw_xml = toc_file.read_text(encoding="utf-8")
        else:
            print(f"  [下载] {name} -> {url}")
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}
                resp = requests.get(url, headers=headers, timeout=30)
                resp.raise_for_status()
                raw_xml = resp.text
                toc_file.write_text(raw_xml, encoding="utf-8")
            except Exception as e:
                print(f"  [错误] {name} 下载失败: {e}")
                continue

        parsed = feedparser.parse(raw_xml)
        feed_title = parsed.feed.get("title", "")
        if name not in feed_title:
            print(f"  [警告] 内容标题不匹配: 期望含 \"{name}\"，实际为 \"{feed_title}\"")

        inserted = save_raw_feed(conn, feed_id, raw_xml)

        if inserted:
            print(f"  [新增] {name} -> 已保存原始内容")
        else:
            print(f"  [跳过] {name} -> 原始内容未变化")


def parse_and_store_articles(conn):
    """从 raw_feeds 表读取所有原始 XML，解析后存入 articles 表。"""
    rows = conn.execute(
        "SELECT rf.feed_id, rf.raw_content, f.name "
        "FROM raw_feeds rf JOIN feeds f ON rf.feed_id = f.id"
    ).fetchall()
    for row in rows:
        parsed = feedparser.parse(row["raw_content"])
        new_count = 0
        for entry in parsed.entries:
            article = parse_entry(entry)
            if save_article(conn, row["feed_id"], article):
                new_count += 1
        print(f"  [{row['name']}] 新增 {new_count} 篇，共 {len(parsed.entries)} 篇")


def sync_users(conn):
    """从 users.json 同步用户和订阅关系到数据库。"""
    with open("users.json") as f:
        users_cfg = json.load(f)["users"]
    for user_cfg in users_cfg:
        user_id = ensure_user(conn, user_cfg["name"])
        for feed_name in user_cfg.get("subscriptions", []):
            row = conn.execute(
                "SELECT id FROM feeds WHERE name = ?", (feed_name,)
            ).fetchone()
            if not row:
                print(f"  [警告] 用户 {user_cfg['name']} 订阅的 \"{feed_name}\" 未在 feeds 表中找到，跳过")
                continue
            added = ensure_subscription(conn, user_id, row["id"])
            if added:
                print(f"  [新增] {user_cfg['name']} -> {feed_name}")


def main():
    init_db()
    conn = get_connection()

    print("=== 拉取并存储 RSS 原始内容 ===")
    fetch_and_store_raw_feeds(conn)
    print()

    print("=== 同步用户与订阅 ===")
    sync_users(conn)
    print()

    print("=== 解析并存储文章 ===")
    parse_and_store_articles(conn)
    print()

    print("=== 最近入库的 3 篇文章 ===")
    rows = conn.execute(
        "SELECT title, authors, link, published, summary "
        "FROM articles ORDER BY id DESC LIMIT 3"
    ).fetchall()
    for i, row in enumerate(rows):
        print(f"--- 第 {i + 1} 篇 ---")
        print(f"  标题: {row['title']}")
        print(f"  作者: {', '.join(json.loads(row['authors']))}")
        print(f"  链接: {row['link']}")
        print(f"  日期: {row['published']}")
        print(f"  摘要: {row['summary'][:100]}...")
        print()

    print("=== 为每位用户生成个人早报 ===")
    load_dotenv()
    REPORTS_DIR.mkdir(exist_ok=True)

    users = conn.execute("SELECT id, name FROM users").fetchall()
    for user in users:
        user_id, user_name = user["id"], user["name"]
        latest_date, articles = fetch_user_latest_articles(conn, user_id)

        if not articles:
            print(f"  [{user_name}] 没有找到相关论文，跳过")
            continue

        print(f"  [{user_name}] 找到 {len(articles)} 篇论文（最新日期 {latest_date}）")
        user_prompt = build_user_prompt(latest_date, articles)

        print(f"  [{user_name}] 正在生成 Markdown 早报...")
        report = generate_report(user_prompt)
        report_path = REPORTS_DIR / f"{latest_date}-{user_name}.md"
        report_path.write_text(report, encoding="utf-8")
        print(f"  [{user_name}] 早报已生成: {report_path}")

        print(f"  [{user_name}] 正在生成语音稿...")
        voice_script = generate_voice_script(user_prompt)
        voice_path = REPORTS_DIR / f"{latest_date}-{user_name}-voice.txt"
        voice_path.write_text(voice_script, encoding="utf-8")
        print(f"  [{user_name}] 语音稿已生成: {voice_path}")

    print()
    conn.close()


if __name__ == "__main__":
    main()
