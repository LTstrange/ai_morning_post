"""子命令处理模块。"""

import json
import shutil
from pathlib import Path

from db import (
    reset_user_history,
    get_push_batches,
    get_batch,
    get_batch_articles,
    migrate,
    get_connection,
    add_user,
    get_user,
    activate_user,
    deactivate_user,
    remove_user,
    list_users,
    ensure_user,
    set_user_subscriptions,
    add_subscription,
    remove_subscription,
    get_user_subscriptions,
    set_user_interests,
    set_user_email,
    rename_user,
    get_articles_without_embedding,
    batch_update_embeddings,
)
from rss import fetch_and_store_raw_feeds, parse_and_store_articles
from users import init_connection, sync_users, generate_for_users, generate_from_batch


def cmd_fetch(args):
    """处理 fetch 子命令。"""
    conn = init_connection()
    print("=== 拉取并存储 RSS 原始内容 ===")
    fetch_and_store_raw_feeds(conn, force=args.force)
    conn.close()


def cmd_parse(args):
    """处理 parse 子命令。"""
    conn = init_connection()
    print("=== 解析并存储文章 ===")
    parse_and_store_articles(conn)
    if args.enrich:
        from rss import enrich_missing_metadata

        print("\n=== 补全缺失元数据 ===")
        enrich_missing_metadata(conn)
    conn.close()


def _resolve_gen_flags(args):
    """解析 report/voice/tts/email 标志，都未指定时默认生成 report 和 voice。"""
    do_email = getattr(args, "email", False)
    if getattr(args, "all", False):
        return True, True, True, do_email
    any_flag = args.report or args.voice or args.tts
    return (
        args.report if any_flag else True,
        args.voice if any_flag else True,
        args.tts,
        do_email,
    )


def cmd_regen(args):
    """处理 regen 子命令。"""
    conn = init_connection()
    gen_report, gen_voice, gen_tts, _do_email = _resolve_gen_flags(args)

    print(f"=== 基于批次 #{args.batch} 重新生成内容 ===")
    generate_from_batch(
        conn,
        batch_id=args.batch,
        gen_report=gen_report,
        gen_voice=gen_voice,
        gen_tts=gen_tts,
    )
    conn.close()


def _resolve_user(conn, username):
    """根据用户名查找用户，未找到时打印提示并返回 None。"""
    if not username:
        return None
    user = conn.execute("SELECT id FROM users WHERE name = ?", (username,)).fetchone()
    if not user:
        print(f'未找到用户 "{username}"')
    return user


def cmd_history(args):
    """处理 history 子命令。"""
    conn = init_connection()

    if args.history_action == "show":
        user = _resolve_user(conn, getattr(args, "username", None))
        if getattr(args, "username", None) and not user:
            conn.close()
            return

        user_id = user["id"] if user else None
        date_str = getattr(args, "date", None)
        date_from = getattr(args, "date_from", None)
        date_to = getattr(args, "date_to", None)

        label_parts = []
        if user:
            label_parts.append(args.username)
        if date_str:
            label_parts.append(date_str)
        if date_from or date_to:
            label_parts.append(f"{date_from or '...'} ~ {date_to or '...'}")
        label = " / ".join(label_parts) if label_parts else "所有用户"
        print(f"=== {label} 的推送历史 ===")

        limit = getattr(args, "limit", 10) or None
        batches = get_push_batches(
            conn,
            user_id=user_id,
            date_str=date_str,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        if not batches:
            print("暂无批次记录")
        else:
            for b in batches:
                status_parts = []
                if b["has_report"]:
                    status_parts.append("早报")
                if b["has_voice"]:
                    status_parts.append("语音稿")
                if b["has_tts"]:
                    status_parts.append("音频")
                status = " | ".join(status_parts) if status_parts else "无产物"
                print(
                    f"  批次 #{b['id']} [{b['user_name']}] {b['created_at']} "
                    f"({b['article_count']} 篇文章) [{status}]"
                )
            if limit and len(batches) >= limit:
                print(f"\n  （仅显示最近 {limit} 个批次，使用 --limit 0 查看全部）")

    elif args.history_action == "batch":
        batch = get_batch(conn, args.batch_id)
        if not batch:
            print(f"未找到批次 #{args.batch_id}")
            conn.close()
            return

        status_parts = []
        if batch["report"]:
            status_parts.append("早报")
        if batch["voice_script"]:
            status_parts.append("语音稿")
        if batch["tts_audio_path"]:
            status_parts.append("音频")
        status = " | ".join(status_parts) if status_parts else "无产物"

        print(f"批次 #{batch['id']}")
        print(f"用户: {batch['user_name']}")
        print(f"创建时间: {batch['created_at']}")
        print(f"产物: {status}")

        articles = get_batch_articles(conn, args.batch_id)
        if articles:
            print(f"关联文章 ({len(articles)} 篇):")
            for i, a in enumerate(articles, 1):
                print(f"  {i}. {a['title']} ({a['feed_name']}, {a['published'][:10]})")
        else:
            print("关联文章: 无")

    elif args.history_action == "reset":
        user = _resolve_user(conn, getattr(args, "username", None))
        if getattr(args, "username", None) and not user:
            conn.close()
            return

        user_id = user["id"] if user else None
        batch_id = getattr(args, "batch", None)
        date_str = getattr(args, "date", None)
        after_date = getattr(args, "after", None)

        reset_user_history(
            conn,
            user_id=user_id,
            batch_id=batch_id,
            date_str=date_str,
            after_date=after_date,
        )

        desc_parts = []
        if user:
            desc_parts.append(f"用户 {args.username}")
        if batch_id:
            desc_parts.append(f"批次 #{batch_id}")
        if date_str:
            desc_parts.append(f"日期 {date_str}")
        if after_date:
            desc_parts.append(f"{after_date} 之后")
        desc = "、".join(desc_parts) if desc_parts else "所有用户"
        print(f"已重置 {desc} 的推送历史")

    conn.close()


def cmd_run(args):
    """处理 run 子命令。"""
    conn = init_connection()
    gen_report, gen_voice, gen_tts, do_email = _resolve_gen_flags(args)

    print("=== 拉取并存储 RSS 原始内容 ===")
    fetch_and_store_raw_feeds(conn)
    print()

    print("=== 解析并存储文章 ===")
    parse_and_store_articles(conn)
    print()

    print("=== 为每位用户生成个人早报 ===")
    generate_for_users(
        conn,
        user_filter=args.user,
        gen_report=gen_report,
        gen_voice=gen_voice,
        gen_tts=gen_tts,
        do_email=do_email,
    )
    print()
    conn.close()


def cmd_migrate(args):
    """处理 migrate 子命令。"""
    conn = get_connection()
    print("=== 检查并执行数据库迁移 ===")
    migrate(conn)
    conn.close()
    print("迁移完成。")


def _resolve_target_user(conn, username):
    """查找目标用户，未找到时打印提示并返回 None。"""
    user = get_user(conn, username)
    if not user:
        print(f'未找到用户 "{username}"')
    return user


def _find_feed(conn, feed_name):
    """查找 feed，未找到时打印提示并返回 None。"""
    feed = conn.execute("SELECT id FROM feeds WHERE name = ?", (feed_name,)).fetchone()
    if not feed:
        print(f'未找到期刊 "{feed_name}"，请先运行 fetch')
    return feed


def _load_user_file(filepath):
    """加载用户配置文件，返回 users 列表。"""
    with open(filepath) as f:
        data = json.load(f)
    return data.get("users", data) if isinstance(data, dict) else data


def cmd_user(args):
    """处理 user 子命令。"""
    conn = init_connection()

    if args.user_action == "add":
        user_id = add_user(conn, args.username)
        if user_id:
            print(f'已创建用户 "{args.username}"')
        else:
            print(f'用户 "{args.username}" 已存在，跳过')

    elif args.user_action == "remove":
        user = _resolve_target_user(conn, args.username)
        if user:
            remove_user(conn, user["id"])
            print(f'用户 "{args.username}" 及其全部数据已删除')

    elif args.user_action == "deactivate":
        user = _resolve_target_user(conn, args.username)
        if user:
            if not user["active"]:
                print(f'用户 "{args.username}" 已在停用状态，无需操作')
            else:
                deactivate_user(conn, user["id"])
                print(f'用户 "{args.username}" 已停用')

    elif args.user_action == "activate":
        user = _resolve_target_user(conn, args.username)
        if user:
            if user["active"]:
                print(f'用户 "{args.username}" 已在活跃状态，无需操作')
            else:
                activate_user(conn, user["id"])
                print(f'用户 "{args.username}" 已激活')

    elif args.user_action == "rename":
        user = _resolve_target_user(conn, args.username)
        if user:
            new_name = args.new_name
            existing = get_user(conn, new_name)
            if existing:
                print(f'用户名 "{new_name}" 已被占用')
            else:
                rename_user(conn, user["id"], new_name)
                print(f'已将用户 "{args.username}" 重命名为 "{new_name}"')

    elif args.user_action == "list":
        users = list_users(conn)
        if not users:
            print("暂无用户")
        else:
            for u in users:
                status = "" if u["active"] else " [已停用]"
                sub_count = conn.execute(
                    "SELECT COUNT(*) FROM subscriptions WHERE user_id = ?",
                    (u["id"],),
                ).fetchone()[0]
                print(f"  {u['name']}{status} ({sub_count} 个订阅)")

    elif args.user_action == "show":
        user = _resolve_target_user(conn, args.username)
        if user:
            status = "活跃" if user["active"] else "已停用"
            print(f"用户: {user['name']}")
            print(f"邮箱: {user['email'] or '未设置'}")
            print(f"状态: {status}")
            print(f"创建时间: {user['created_at']}")
            subs = get_user_subscriptions(conn, user["id"])
            if not subs:
                print("订阅: 无")
            else:
                print("订阅:")
                for s in subs:
                    print(f"  - {s['name']}")

    elif args.user_action == "subscribe":
        user = _resolve_target_user(conn, args.username)
        if user:
            feed_name = getattr(args, "feed_name", None)
            feed = _find_feed(conn, feed_name)
            if feed:
                result = add_subscription(conn, user["id"], feed_name)
                if result:
                    print(f'已为用户 "{args.username}" 添加订阅: {feed_name}')
                else:
                    print(f"订阅已存在: {feed_name}")

    elif args.user_action == "unsubscribe":
        user = _resolve_target_user(conn, args.username)
        if user:
            feed_name = getattr(args, "feed_name", None)
            result = remove_subscription(conn, user["id"], feed_name)
            if result:
                print(f'已为用户 "{args.username}" 取消订阅: {feed_name}')
            else:
                print(f"未找到该订阅: {feed_name}")

    elif args.user_action == "sync":
        filepath = getattr(args, "file", "users.json")
        try:
            sync_users(conn, filepath)
        except FileNotFoundError:
            print(f"文件不存在: {filepath}")

    elif args.user_action == "restore":
        filepath = args.file
        try:
            users_data = _load_user_file(filepath)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"加载文件失败: {e}")
            conn.close()
            return

        for uc in users_data:
            name = uc["name"]
            user_id = ensure_user(conn, name)
            activate_user(conn, user_id)
            set_user_subscriptions(conn, user_id, uc.get("subscriptions", []))
            if "interests" in uc:
                set_user_interests(conn, user_id, uc["interests"])
            if "email" in uc:
                set_user_email(conn, user_id, uc["email"])
            print(
                f'已恢复用户 "{name}" 的配置 ({len(uc.get("subscriptions", []))} 个订阅)'
            )

    elif args.user_action == "export":
        users = conn.execute(
            "SELECT id, name, email, interests FROM users WHERE active = 1 ORDER BY name"
        ).fetchall()
        if not users:
            print("没有活跃用户可导出")
        else:
            export_data = {"users": []}
            for u in users:
                subs = get_user_subscriptions(conn, u["id"])
                user_entry = {
                    "name": u["name"],
                    "subscriptions": [s["name"] for s in subs],
                }
                if u["email"]:
                    user_entry["email"] = u["email"]
                if u["interests"]:
                    user_entry["interests"] = u["interests"]
                export_data["users"].append(user_entry)
            with open(args.file, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            print(f"已导出 {len(users)} 个用户到 {args.file}")

    conn.close()


def cmd_send(args):
    """处理 send 子命令：发送已有批次的早报邮件。"""
    from dotenv import load_dotenv
    from mailer import send_report_email

    load_dotenv()
    conn = init_connection()
    batch = get_batch(conn, args.batch)
    if not batch:
        print(f"未找到批次 #{args.batch}")
        conn.close()
        return

    if not batch["report"]:
        print(f"批次 #{args.batch} 没有早报内容，无法发送")
        conn.close()
        return

    user_name = batch["user_name"]
    user = conn.execute(
        "SELECT email FROM users WHERE id = ?", (batch["user_id"],)
    ).fetchone()
    email = user["email"] if user else None

    if not email:
        print(f'用户 "{user_name}" 未配置邮箱')
        conn.close()
        return

    tts_path = batch["tts_audio_path"] if args.tts else None
    subject = f"AI 早报 - {batch['created_at'][:10]}"

    print(f"正在发送批次 #{args.batch} 的早报邮件到 {email}...")
    ok = send_report_email(email, subject, batch["report"], tts_path=tts_path)
    if ok:
        print("邮件发送成功")

    conn.close()


def cmd_export(args):
    """处理 export 子命令：从数据库导出批次产物到文件。"""
    conn = init_connection()
    batch = get_batch(conn, args.batch)
    if not batch:
        print(f"未找到批次 #{args.batch}")
        conn.close()
        return

    user_name = batch["user_name"]
    batch_date = batch["created_at"][:10]
    any_flag = args.report or args.voice or args.tts
    export_report = args.report if any_flag else True
    export_voice = args.voice if any_flag else True
    export_tts = args.tts if any_flag else True

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    exported = 0

    if export_report:
        if batch["report"]:
            path = output_dir / f"{batch_date}-{user_name}-report.md"
            path.write_text(batch["report"], encoding="utf-8")
            print(f"  已导出早报: {path}")
            exported += 1
        else:
            print("  该批次没有早报内容")

    if export_voice:
        if batch["voice_script"]:
            path = output_dir / f"{batch_date}-{user_name}-voice.txt"
            path.write_text(batch["voice_script"], encoding="utf-8")
            print(f"  已导出语音稿: {path}")
            exported += 1
        else:
            print("  该批次没有语音稿内容")

    if export_tts:
        if batch["tts_audio_path"]:
            src = Path(batch["tts_audio_path"])
            if src.exists():
                dst = output_dir / f"{batch_date}-{user_name}.mp3"
                shutil.copy2(src, dst)
                print(f"  已导出音频: {dst}")
                exported += 1
            else:
                print(f"  音频文件不存在: {src}")
        else:
            print("  该批次没有音频文件")

    if exported == 0:
        print("没有可导出的内容")

    conn.close()


def cmd_backfill(args):
    """处理 backfill 子命令：为缺少 embedding 的文章批量计算向量。"""
    from embedding import compute_embedding

    conn = init_connection()
    batch_size = getattr(args, "batch_size", 100)

    total = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE embedding IS NULL"
    ).fetchone()[0]

    if total == 0:
        print("所有文章已有 embedding，无需回填")
        conn.close()
        return

    print(f"=== 回填 embedding：共 {total} 篇文章待处理 ===")
    processed = 0

    while True:
        articles = get_articles_without_embedding(conn, limit=batch_size)
        if not articles:
            break

        updates = []
        for a in articles:
            text = f"{a['title']} {a['summary'] or ''}"
            emb = compute_embedding(text)
            updates.append((emb, a["id"]))

        batch_update_embeddings(conn, updates)
        processed += len(updates)
        print(f"  已处理 {processed}/{total} 篇")

    print(f"回填完成，共处理 {processed} 篇文章")
    conn.close()
