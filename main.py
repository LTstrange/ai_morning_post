"""拉取 RSS、同步用户、智能筛选文章、生成 AI 早报和语音。"""

import argparse
import json
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import requests

from dotenv import load_dotenv

from db import (
    get_connection,
    init_db,
    ensure_feed,
    save_raw_feed,
    save_article,
    ensure_user,
    ensure_subscription,
    mark_article_pushed,
    reset_user_history,
    get_user_history,
)
from generate_report import (
    build_user_prompt,
    fetch_candidate_articles,
    select_articles,
    generate_report,
    generate_voice_script,
    REPORTS_DIR,
)
from tts import text_to_speech


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
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                }
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
                print(
                    f'  [警告] 用户 {user_cfg["name"]} 订阅的 "{feed_name}" 未在 feeds 表中找到，跳过'
                )
                continue
            added = ensure_subscription(conn, user_id, row["id"])
            if added:
                print(f"  [新增] {user_cfg['name']} -> {feed_name}")


def main():
    parser = argparse.ArgumentParser(description="拉取 RSS、同步用户、生成 AI 早报")
    parser.add_argument("-u", "--user", help="只为指定用户名生成早报")
    parser.add_argument("--report", action="store_true", help="只生成 Markdown 早报")
    parser.add_argument("--voice", action="store_true", help="只生成语音播报稿")
    parser.add_argument("--tts", action="store_true", help="生成语音音频（需要 MIMO_API_KEY）")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行，不标记文章为已推送")
    parser.add_argument("--reset-history", nargs="?", const="ALL", metavar="USERNAME",
                        help="重置推送历史（指定用户名或留空重置所有）")
    parser.add_argument("--show-history", nargs="?", const="ALL", metavar="USERNAME",
                        help="查看推送历史（指定用户名或留空查看所有）")
    args = parser.parse_args()

    init_db()
    conn = get_connection()

    # 处理调试命令
    if args.show_history:
        if args.show_history == "ALL":
            print("=== 所有用户推送历史 ===")
            history = get_user_history(conn)
        else:
            user = conn.execute("SELECT id FROM users WHERE name = ?", (args.show_history,)).fetchone()
            if not user:
                print(f"未找到用户 \"{args.show_history}\"")
                conn.close()
                return
            print(f"=== {args.show_history} 的推送历史 ===")
            history = get_user_history(conn, user["id"])

        if not history:
            print("暂无推送记录")
        else:
            for h in history:
                print(f"  [{h['user_name']}] {h['title']} ({h['pushed_at']})")
        conn.close()
        return

    if args.reset_history is not None:
        if args.reset_history == "ALL":
            reset_user_history(conn)
            print("已重置所有用户的推送历史")
        else:
            user = conn.execute("SELECT id FROM users WHERE name = ?", (args.reset_history,)).fetchone()
            if not user:
                print(f"未找到用户 \"{args.reset_history}\"")
                conn.close()
                return
            reset_user_history(conn, user["id"])
            print(f"已重置 {args.reset_history} 的推送历史")
        conn.close()
        return

    # 如果 report/voice/tts 都没指定，默认生成 report 和 voice
    any_flag = args.report or args.voice or args.tts
    gen_report = args.report if any_flag else True
    gen_voice = args.voice if any_flag else True
    gen_tts = args.tts

    print("=== 拉取并存储 RSS 原始内容 ===")
    fetch_and_store_raw_feeds(conn)
    print()

    print("=== 同步用户与订阅 ===")
    sync_users(conn)
    print()

    print("=== 解析并存储文章 ===")
    parse_and_store_articles(conn)
    print()

    print("=== 为每位用户生成个人早报 ===")
    load_dotenv()
    REPORTS_DIR.mkdir(exist_ok=True)

    today = date.today().isoformat()

    if args.user:
        users = conn.execute(
            "SELECT id, name FROM users WHERE name = ?", (args.user,)
        ).fetchall()
        if not users:
            print(f"未找到用户 \"{args.user}\"，跳过早报生成")
            conn.close()
            return
    else:
        users = conn.execute("SELECT id, name FROM users").fetchall()

    for user in users:
        user_id, user_name = user["id"], user["name"]

        # 智能筛选候选文章
        print(f"  [{user_name}] 正在筛选候选文章...")
        candidates, today_articles = fetch_candidate_articles(conn, user_id, today)

        if not candidates:
            print(f"  [{user_name}] 没有找到候选论文，跳过")
            continue

        print(f"  [{user_name}] 找到 {len(today_articles)} 篇当天论文，"
              f"共 {len(candidates)} 篇候选论文")

        # AI 选择 2-3 篇
        print(f"  [{user_name}] 正在选择推荐文章...")
        selected = select_articles(candidates)
        print(f"  [{user_name}] 已选择 {len(selected)} 篇推荐文章")

        # 标记已推送
        if not args.dry_run:
            for article in selected:
                mark_article_pushed(conn, user_id, article["id"])
            print(f"  [{user_name}] 已标记 {len(selected)} 篇文章为已推送")
        else:
            print(f"  [{user_name}] [DRY RUN] 跳过标记已推送文章")

        # 生成报告
        user_prompt = build_user_prompt(today, selected)

        if gen_report:
            print(f"  [{user_name}] 正在生成 Markdown 早报...")
            report = generate_report(user_prompt)
            report_path = REPORTS_DIR / f"{today}-{user_name}.md"
            report_path.write_text(report, encoding="utf-8")
            print(f"  [{user_name}] 早报已生成: {report_path}")

        if gen_voice:
            print(f"  [{user_name}] 正在生成语音稿...")
            voice_script = generate_voice_script(user_prompt)
            voice_path = REPORTS_DIR / f"{today}-{user_name}-voice.txt"
            voice_path.write_text(voice_script, encoding="utf-8")
            print(f"  [{user_name}] 语音稿已生成: {voice_path}")

        if gen_tts:
            # 如果播报稿还没生成，先读取或生成
            if not gen_voice:
                voice_path = REPORTS_DIR / f"{today}-{user_name}-voice.txt"
                if voice_path.exists():
                    voice_script = voice_path.read_text(encoding="utf-8")
                else:
                    print(f"  [{user_name}] 正在生成语音稿...")
                    voice_script = generate_voice_script(user_prompt)
                    voice_path.write_text(voice_script, encoding="utf-8")
            audio_path = REPORTS_DIR / f"{today}-{user_name}-voice.wav"
            print(f"  [{user_name}] 正在生成语音音频...")
            text_to_speech(voice_script, audio_path)
            print(f"  [{user_name}] 语音音频已生成: {audio_path}")

    print()
    conn.close()


if __name__ == "__main__":
    main()
