"""RSS 数据获取和解析模块。"""

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

from abstract_fetcher import fetch_metadata_by_doi
from db import (
    ensure_feed,
    get_latest_raw_feed,
    save_raw_feed,
    save_article,
    article_exists,
)

CACHE_TTL = timedelta(hours=23)

_DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s]+)")


def load_feeds(path="feeds.json"):
    """读取配置文件，返回展平的 feed 列表，每项附带 publisher 字段。"""
    with open(path) as f:
        data = json.load(f)
    result = []
    for publisher, group in data["publishers"].items():
        for feed in group["feeds"]:
            result.append({**feed, "publisher": publisher})
    return result


def _parse_date_rfc2822(raw):
    """将 RFC 2822 日期字符串转为 ISO 8601 格式，解析失败时返回原始字符串。"""
    try:
        return parsedate_to_datetime(raw).isoformat()
    except Exception:
        return raw


def _extract_doi(entry):
    """从 feedparser entry 中尽力提取 DOI。"""
    for key in ("prism_doi", "doi", "dc_identifier"):
        val = entry.get(key, "")
        if val and val.startswith("10."):
            return val.strip()
    for field in ("link", "id"):
        val = entry.get(field, "")
        m = _DOI_RE.search(val)
        if m:
            return m.group(1)
    return ""


# ---------------------------------------------------------------------------
# 出版商专用解析函数
# ---------------------------------------------------------------------------


def _parse_entry_ieee(entry):
    """IEEE RSS：summary 是摘要，published 是 RFC 2822 日期，authors 分号分隔。"""
    raw_authors = entry.get("authors", "")
    if isinstance(raw_authors, list):
        author_list = [
            a["name"] for a in raw_authors if isinstance(a, dict) and a.get("name")
        ]
    else:
        author_list = [a.strip() for a in raw_authors.split(";") if a.strip()]

    return {
        "title": entry.get("title", ""),
        "link": entry.get("link", ""),
        "summary": entry.get("summary") or None,
        "published": _parse_date_rfc2822(entry.get("published", "")),
        "doi": _extract_doi(entry),
        "authors": author_list,
    }


def _parse_entry_informs(entry):
    """INFORMS RSS：summary 无摘要（需 DOI 补全），日期在 updated/prism_coverdate，authors 是 dict 列表。"""
    raw_authors = entry.get("authors", [])
    if isinstance(raw_authors, list):
        author_list = [
            a["name"] for a in raw_authors if isinstance(a, dict) and a.get("name")
        ]
    else:
        author_list = [a.strip() for a in raw_authors.split(";") if a.strip()]

    published = ""
    for field in ("updated", "prism_coverdate", "prism_coverdisplaydate"):
        val = entry.get(field, "")
        if val:
            published = val
            break

    return {
        "title": entry.get("title", ""),
        "link": entry.get("link", ""),
        "summary": None,
        "published": published,
        "doi": _extract_doi(entry),
        "authors": author_list,
    }


def _strip_html(text):
    """剥离 HTML 标签，返回纯文本。"""
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_entry_aap(entry):
    """AAP (Silverchair) RSS：description 含 HTML 摘要，prism:doi 提供 DOI，无作者字段。"""
    raw_summary = entry.get("summary") or entry.get("description") or ""
    summary = _strip_html(raw_summary) or None

    return {
        "title": entry.get("title", ""),
        "link": entry.get("link", ""),
        "summary": summary,
        "published": _parse_date_rfc2822(entry.get("published", "")),
        "doi": _extract_doi(entry),
        "authors": [],
    }


def _parse_authors_dict_list(raw_authors):
    """从 feedparser 的 [{"name": "..."}] 格式提取作者列表。"""
    if not isinstance(raw_authors, list):
        return []
    return [a["name"] for a in raw_authors if isinstance(a, dict) and a.get("name")]


def _parse_entry_aaas(entry):
    """AAAS (Science) RSS (RDF 1.0)：无摘要，有 authors，日期在 updated。"""
    return {
        "title": entry.get("title", ""),
        "link": entry.get("link", ""),
        "summary": None,
        "published": entry.get("updated", ""),
        "doi": _extract_doi(entry),
        "authors": _parse_authors_dict_list(entry.get("authors", [])),
    }


ENTRY_PARSERS = {
    "ieee": {
        "parser": _parse_entry_ieee,
        "enrich_abstract": False,
    },
    "informs": {
        "parser": _parse_entry_informs,
        "enrich_abstract": True,
    },
    "aap": {
        "parser": _parse_entry_aap,
        "enrich_abstract": False,
        "enrich_authors": True,
    },
    "aaas": {
        "parser": _parse_entry_aaas,
        "enrich_abstract": True,
    },
}


def _get_publisher_config(publisher):
    """根据出版商名称返回配置，未知出版商抛出异常。"""
    if publisher not in ENTRY_PARSERS:
        raise ValueError(
            f"未知出版商: {publisher!r}，请在 ENTRY_PARSERS 中注册解析函数"
        )
    return ENTRY_PARSERS[publisher]


# ---------------------------------------------------------------------------
# fetch / parse 主流程
# ---------------------------------------------------------------------------


def fetch_and_store_raw_feeds(conn, force=False):
    """遍历所有 feed 源，从 URL 拉取 RSS 存入 raw_feeds 表（23 小时内缓存有效则跳过）。"""
    feeds = load_feeds()
    now = datetime.now(timezone.utc)

    for feed_cfg in feeds:
        name = feed_cfg["name"]
        url = feed_cfg["url"]
        publisher = feed_cfg.get("publisher")

        feed_id = ensure_feed(conn, name, url, publisher)

        if not force:
            latest_fetched_at = get_latest_raw_feed(conn, feed_id)
            if latest_fetched_at:
                fetched_time = datetime.fromisoformat(latest_fetched_at).replace(
                    tzinfo=timezone.utc
                )
                if now - fetched_time < CACHE_TTL:
                    local_time = fetched_time.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"  [跳过] {name} -> 缓存未过期（{local_time}）")
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
    """从 raw_feeds 表读取所有原始 XML，解析后存入 articles 表。
    摘要为空时通过 CrossRef API 按 DOI 补全。
    """
    rows = conn.execute(
        "SELECT rf.feed_id, rf.raw_content, f.name, f.publisher "
        "FROM raw_feeds rf JOIN feeds f ON rf.feed_id = f.id"
    ).fetchall()
    for row in rows:
        publisher = row["publisher"] or ""
        try:
            config = _get_publisher_config(publisher)
        except ValueError as e:
            print(f"  [跳过] {row['name']}: {e}")
            continue

        parse_entry = config["parser"]
        enrich_abs = config.get("enrich_abstract", False)
        enrich_auth = config.get("enrich_authors", False)

        parsed = feedparser.parse(row["raw_content"])
        new_count = 0
        abstract_enriched = 0
        authors_enriched = 0
        for entry in parsed.entries:
            article = parse_entry(entry)
            if article_exists(conn, article["link"]):
                continue
            need_abstract = enrich_abs and not article["summary"]
            need_authors = enrich_auth and not article["authors"]
            if (need_abstract or need_authors) and article["doi"]:
                meta = fetch_metadata_by_doi(article["doi"])
                if need_abstract and meta["abstract"]:
                    article["summary"] = meta["abstract"]
                    abstract_enriched += 1
                elif need_abstract:
                    print(f"    [警告] 无法获取摘要: {article['title'][:60]}")
                if need_authors and meta["authors"]:
                    article["authors"] = meta["authors"]
                    authors_enriched += 1
                elif need_authors:
                    print(f"    [警告] 无法获取作者: {article['title'][:60]}")
            if save_article(conn, row["feed_id"], article):
                new_count += 1
        msg = f"  [{row['name']}] 新增 {new_count} 篇，共 {len(parsed.entries)} 篇"
        if abstract_enriched:
            msg += f"（{abstract_enriched} 篇补全摘要）"
        if authors_enriched:
            msg += f"（{authors_enriched} 篇补全作者）"
        print(msg)


def enrich_missing_metadata(conn):
    """根据 ENTRY_PARSERS 配置，为对应出版商的文章通过 CrossRef DOI 补全缺失的摘要和作者。"""
    abstract_publishers = [
        p for p, cfg in ENTRY_PARSERS.items() if cfg.get("enrich_abstract")
    ]
    authors_publishers = [
        p for p, cfg in ENTRY_PARSERS.items() if cfg.get("enrich_authors")
    ]

    if not abstract_publishers and not authors_publishers:
        print("  没有出版商需要补全")
        return

    conditions = []
    params = []
    if abstract_publishers:
        placeholders = ",".join("?" * len(abstract_publishers))
        conditions.append(f"(f.publisher IN ({placeholders}) AND a.summary IS NULL)")
        params.extend(abstract_publishers)
    if authors_publishers:
        placeholders = ",".join("?" * len(authors_publishers))
        conditions.append(f"(f.publisher IN ({placeholders}) AND a.authors = '[]')")
        params.extend(authors_publishers)

    rows = conn.execute(
        "SELECT a.id, a.title, a.doi, a.summary, a.authors, f.publisher "
        "FROM articles a JOIN feeds f ON a.feed_id = f.id "
        f"WHERE a.doi != '' AND ({' OR '.join(conditions)})",
        params,
    ).fetchall()

    if not rows:
        print("  没有需要补全的文章")
        return

    print(f"  找到 {len(rows)} 篇待补全文章...")
    abstract_ok = 0
    authors_ok = 0
    for row in rows:
        publisher = row["publisher"]
        cfg = ENTRY_PARSERS.get(publisher, {})
        need_abstract = cfg.get("enrich_abstract") and row["summary"] is None
        need_authors = cfg.get("enrich_authors") and row["authors"] == "[]"
        if not need_abstract and not need_authors:
            continue
        meta = fetch_metadata_by_doi(row["doi"])
        if need_abstract and meta["abstract"]:
            conn.execute(
                "UPDATE articles SET summary = ? WHERE id = ?",
                (meta["abstract"], row["id"]),
            )
            conn.commit()
            abstract_ok += 1
            print(f"    [摘要] {row['title'][:60]}")
        if need_authors and meta["authors"]:
            conn.execute(
                "UPDATE articles SET authors = ? WHERE id = ?",
                (json.dumps(meta["authors"], ensure_ascii=False), row["id"]),
            )
            conn.commit()
            authors_ok += 1
            print(f"    [作者] {row['title'][:60]}")
    print(f"  完成：{abstract_ok} 篇补全摘要，{authors_ok} 篇补全作者")
