"""用户订阅管理和早报生成模块。"""

import json
from datetime import date

from dotenv import load_dotenv

from db import (
    get_connection,
    init_db,
    ensure_user,
    ensure_subscription,
    create_push_batch,
    mark_article_pushed,
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


def init_connection():
    """初始化数据库连接，返回连接对象。"""
    init_db()
    return get_connection()


def generate_for_users(
    conn,
    user_filter=None,
    gen_report=True,
    gen_voice=True,
    gen_tts=False,
    dry_run=False,
):
    """为用户生成早报内容的核心逻辑。"""
    load_dotenv()
    REPORTS_DIR.mkdir(exist_ok=True)

    today = date.today().isoformat()

    if user_filter:
        users = conn.execute(
            "SELECT id, name FROM users WHERE name = ?", (user_filter,)
        ).fetchall()
        if not users:
            print(f'未找到用户 "{user_filter}"，跳过早报生成')
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

        print(
            f"  [{user_name}] 找到 {len(today_articles)} 篇当天论文，"
            f"共 {len(candidates)} 篇候选论文"
        )

        # AI 选择 2-3 篇
        print(f"  [{user_name}] 正在选择推荐文章...")
        selected = select_articles(candidates)
        print(f"  [{user_name}] 已选择 {len(selected)} 篇推荐文章")

        # 标记已推送
        if not dry_run:
            batch_id = create_push_batch(conn, user_id)
            for article in selected:
                mark_article_pushed(conn, user_id, article["id"], batch_id)
            print(
                f"  [{user_name}] 已标记 {len(selected)} 篇文章为已推送（批次 #{batch_id}）"
            )
        else:
            print(f"  [{user_name}] [DRY RUN] 跳过标记已推送文章")

        # 生成报告
        user_prompt = build_user_prompt(today, selected)
        report_path = REPORTS_DIR / f"{today}-{user_name}.md"
        report = None

        if gen_report:
            print(f"  [{user_name}] 正在生成 Markdown 早报...")
            report = generate_report(user_prompt)
            report_path.write_text(report, encoding="utf-8")
            print(f"  [{user_name}] 早报已生成: {report_path}")

        if gen_voice or gen_tts:
            # 语音稿依赖早报文本，确保早报可用
            if report is None:
                if report_path.exists():
                    report = report_path.read_text(encoding="utf-8")
                    print(f"  [{user_name}] 读取已有早报: {report_path}")
                else:
                    print(f"  [{user_name}] 未找到早报，正在生成 Markdown 早报...")
                    report = generate_report(user_prompt)
                    report_path.write_text(report, encoding="utf-8")
                    print(f"  [{user_name}] 早报已生成: {report_path}")

        if gen_voice:
            print(f"  [{user_name}] 正在生成语音稿...")
            voice_script = generate_voice_script(report, user_prompt)
            voice_path = REPORTS_DIR / f"{today}-{user_name}-voice.txt"
            voice_path.write_text(voice_script, encoding="utf-8")
            print(f"  [{user_name}] 语音稿已生成: {voice_path}")

        if gen_tts:
            if not gen_voice:
                voice_path = REPORTS_DIR / f"{today}-{user_name}-voice.txt"
                if voice_path.exists():
                    voice_script = voice_path.read_text(encoding="utf-8")
                else:
                    print(f"  [{user_name}] 正在生成语音稿...")
                    voice_script = generate_voice_script(report, user_prompt)
                    voice_path.write_text(voice_script, encoding="utf-8")
            audio_path = REPORTS_DIR / f"{today}-{user_name}-voice.wav"
            print(f"  [{user_name}] 正在生成语音音频...")
            if text_to_speech(voice_script, audio_path):
                print(f"  [{user_name}] 语音音频已生成: {audio_path}")
            else:
                print(f"  [{user_name}] 语音音频生成失败")
