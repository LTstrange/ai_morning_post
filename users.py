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
    get_batch,
    get_batch_articles,
    update_batch_report,
    update_batch_voice,
    update_batch_tts,
    set_user_interests,
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


def sync_users(conn, filepath="users.json"):
    """从 JSON 文件同步用户和订阅关系到数据库。"""
    with open(filepath) as f:
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
        # 增量导入兴趣：已有则不覆盖
        if "interests" in user_cfg:
            existing = conn.execute(
                "SELECT interests FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if not existing["interests"]:
                set_user_interests(conn, user_id, user_cfg["interests"])
                print(f"  [新增] {user_cfg['name']} 的研究兴趣")


def init_connection():
    """初始化数据库连接，返回连接对象。"""
    init_db()
    return get_connection()


def _ensure_report(conn, batch_id, user_name, date_str, user_prompt, report):
    """确保早报可用：已有则直接返回，否则生成并存入 DB + 写文件。"""
    if report is not None:
        return report
    print(f"  [{user_name}] 正在生成 Markdown 早报...")
    report = generate_report(user_prompt)
    if batch_id:
        update_batch_report(conn, batch_id, report)
    report_path = REPORTS_DIR / f"{date_str}-{user_name}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"  [{user_name}] 早报已生成: {report_path}")
    return report


def _ensure_voice(
    conn, batch_id, user_name, date_str, user_prompt, report, voice_script
):
    """确保语音稿可用：已有则直接返回，否则生成并存入 DB + 写文件。"""
    if voice_script is not None:
        return voice_script
    print(f"  [{user_name}] 正在生成语音稿...")
    voice_script = generate_voice_script(report, user_prompt)
    if batch_id:
        update_batch_voice(conn, batch_id, voice_script)
    voice_path = REPORTS_DIR / f"{date_str}-{user_name}-voice.txt"
    voice_path.write_text(voice_script, encoding="utf-8")
    print(f"  [{user_name}] 语音稿已生成: {voice_path}")
    return voice_script


def _do_tts(conn, batch_id, user_name, date_str, voice_script):
    """生成 TTS 音频并存入 DB。"""
    audio_path = REPORTS_DIR / f"{date_str}-{user_name}-voice.wav"
    print(f"  [{user_name}] 正在生成语音音频...")
    if text_to_speech(voice_script, audio_path):
        if batch_id:
            update_batch_tts(conn, batch_id, audio_path)
        print(f"  [{user_name}] 语音音频已生成: {audio_path}")
    else:
        print(f"  [{user_name}] 语音音频生成失败")


def _generate_outputs(
    conn,
    batch_id,
    user_name,
    date_str,
    user_prompt,
    report,
    voice_script,
    gen_report,
    gen_voice,
    gen_tts,
):
    """根据标志生成产物，自动处理依赖链。"""
    if gen_report:
        report = _ensure_report(conn, batch_id, user_name, date_str, user_prompt, None)
        voice_script = None

    if gen_voice or gen_tts:
        report = _ensure_report(
            conn, batch_id, user_name, date_str, user_prompt, report
        )

    if gen_voice:
        voice_script = _ensure_voice(
            conn, batch_id, user_name, date_str, user_prompt, report, None
        )

    if gen_tts:
        voice_script = _ensure_voice(
            conn, batch_id, user_name, date_str, user_prompt, report, voice_script
        )
        _do_tts(conn, batch_id, user_name, date_str, voice_script)


def generate_for_users(
    conn,
    user_filter=None,
    gen_report=True,
    gen_voice=True,
    gen_tts=False,
    dry_run=False,
):
    """为用户生成早报内容的核心逻辑：选文 + 创建批次 + 生成产物。"""
    load_dotenv()
    REPORTS_DIR.mkdir(exist_ok=True)

    today = date.today().isoformat()

    if user_filter:
        users = conn.execute(
            "SELECT id, name, interests FROM users WHERE name = ?", (user_filter,)
        ).fetchall()
        if not users:
            print(f'未找到用户 "{user_filter}"，跳过早报生成')
            return
    else:
        users = conn.execute(
            "SELECT id, name, interests FROM users WHERE active = 1"
        ).fetchall()

    for user in users:
        user_id, user_name, interests = user["id"], user["name"], user["interests"]

        print(f"  [{user_name}] 正在筛选候选文章...")
        candidates, today_articles = fetch_candidate_articles(
            conn, user_id, today, interests=interests
        )

        if not candidates:
            print(f"  [{user_name}] 没有找到候选论文，跳过")
            continue

        print(
            f"  [{user_name}] 找到 {len(today_articles)} 篇当天论文，"
            f"共 {len(candidates)} 篇候选论文"
        )

        print(f"  [{user_name}] 正在选择推荐文章...")
        selected = select_articles(candidates, interests)
        print(f"  [{user_name}] 已选择 {len(selected)} 篇推荐文章")

        if not dry_run:
            current_batch_id = create_push_batch(conn, user_id)
            for article in selected:
                mark_article_pushed(conn, user_id, article["id"], current_batch_id)
            print(
                f"  [{user_name}] 已标记 {len(selected)} 篇文章为已推送（批次 #{current_batch_id}）"
            )
        else:
            current_batch_id = None
            print(f"  [{user_name}] [DRY RUN] 跳过标记已推送文章")

        user_prompt = build_user_prompt(today, selected)
        _generate_outputs(
            conn,
            current_batch_id,
            user_name,
            today,
            user_prompt,
            None,
            None,
            gen_report,
            gen_voice,
            gen_tts,
        )


def generate_from_batch(conn, batch_id, gen_report=True, gen_voice=True, gen_tts=False):
    """基于已有批次重新生成产物。"""
    load_dotenv()
    REPORTS_DIR.mkdir(exist_ok=True)

    batch = get_batch(conn, batch_id)
    if not batch:
        print(f"未找到批次 #{batch_id}")
        return

    user_name = batch["user_name"]
    batch_date = batch["created_at"][:10]
    print(f"  [批次 #{batch_id}] 用户: {user_name}, 创建于: {batch_date}")

    articles = get_batch_articles(conn, batch_id)
    if not articles:
        print(f"  [批次 #{batch_id}] 没有关联文章，跳过")
        return

    user_prompt = build_user_prompt(batch_date, articles)
    _generate_outputs(
        conn,
        batch_id,
        user_name,
        batch_date,
        user_prompt,
        batch["report"],
        batch["voice_script"],
        gen_report,
        gen_voice,
        gen_tts,
    )
