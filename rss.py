"""RSS 数据获取和解析模块。"""

import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

from db import ensure_feed, get_latest_raw_feed, save_raw_feed, save_article

CACHE_TTL = timedelta(hours=24)


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
    """遍历所有 feed 源，从 URL 拉取 RSS 存入 raw_feeds 表（24 小时内缓存有效则跳过）。"""
    feeds = load_feeds()
    now = datetime.now(timezone.utc)

    for feed_cfg in feeds:
        name = feed_cfg["name"]
        url = feed_cfg["url"]

        feed_id = ensure_feed(conn, name, url)

        latest_fetched_at = get_latest_raw_feed(conn, feed_id)
        if latest_fetched_at:
            fetched_time = datetime.fromisoformat(latest_fetched_at).replace(tzinfo=timezone.utc)
            if now - fetched_time < CACHE_TTL:
                print(f"  [跳过] {name} -> 缓存未过期（{latest_fetched_at}）")
                continue

        print(f"  [下载] {name} -> {url}")
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            raw_xml = resp.text
        except Exception as e:
            print(f"  [错误] {name} 下载失败: {e}")
            continue

        parsed = feedparser.parse(raw_xml)
        feed_title = parsed.feed.get("title", "")
        if name not in feed_title:
            print(f'  [警告] 内容标题不匹配: 期望含 "{name}"，实际为 "{feed_title}"')

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