"""子命令处理模块。"""

from db import reset_user_history, get_user_history, get_push_batches
from rss import fetch_and_store_raw_feeds, parse_and_store_articles
from users import init_connection, sync_users, generate_for_users


def cmd_fetch(args):
    """处理 fetch 子命令。"""
    conn = init_connection()
    print("=== 拉取并存储 RSS 原始内容 ===")
    fetch_and_store_raw_feeds(conn, force=args.force)
    conn.close()


def cmd_sync(args):
    """处理 sync 子命令。"""
    conn = init_connection()
    print("=== 同步用户与订阅 ===")
    sync_users(conn)
    conn.close()


def cmd_parse(args):
    """处理 parse 子命令。"""
    conn = init_connection()
    print("=== 解析并存储文章 ===")
    parse_and_store_articles(conn)
    conn.close()


def cmd_generate(args):
    """处理 generate 子命令。"""
    conn = init_connection()

    # 如果 report/voice/tts 都没指定，默认生成 report 和 voice
    any_flag = args.report or args.voice or args.tts
    gen_report = args.report if any_flag else True
    gen_voice = args.voice if any_flag else True
    gen_tts = args.tts

    print("=== 为每位用户生成个人早报 ===")
    generate_for_users(
        conn,
        user_filter=args.user,
        gen_report=gen_report,
        gen_voice=gen_voice,
        gen_tts=gen_tts,
        dry_run=args.dry_run,
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
        batch_id = getattr(args, "batch", None)
        date_str = getattr(args, "date", None)
        date_from = getattr(args, "date_from", None)
        date_to = getattr(args, "date_to", None)

        label_parts = []
        if user:
            label_parts.append(args.username)
        if batch_id:
            label_parts.append(f"批次 #{batch_id}")
        if date_str:
            label_parts.append(date_str)
        if date_from or date_to:
            label_parts.append(f"{date_from or '...'} ~ {date_to or '...'}")
        label = " / ".join(label_parts) if label_parts else "所有用户"
        print(f"=== {label} 的推送历史 ===")

        history = get_user_history(
            conn,
            user_id=user_id,
            batch_id=batch_id,
            date_str=date_str,
            date_from=date_from,
            date_to=date_to,
        )
        if not history:
            print("暂无推送记录")
        else:
            for h in history:
                print(
                    f"  [批次 #{h['batch_id']}] [{h['user_name']}] {h['title']} ({h['pushed_at']})"
                )

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

    elif args.history_action == "batches":
        user = _resolve_user(conn, getattr(args, "username", None))
        if getattr(args, "username", None) and not user:
            conn.close()
            return

        user_id = user["id"] if user else None
        label = args.username if user else "所有用户"
        print(f"=== {label} 的推送批次 ===")

        batches = get_push_batches(conn, user_id=user_id)
        if not batches:
            print("暂无批次记录")
        else:
            for b in batches:
                print(
                    f"  批次 #{b['id']} [{b['user_name']}] {b['created_at']} ({b['article_count']} 篇文章)"
                )

    conn.close()


def cmd_run(args):
    """处理 run 子命令。"""
    conn = init_connection()

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
    generate_for_users(
        conn,
        user_filter=args.user,
        gen_report=gen_report,
        gen_voice=gen_voice,
        gen_tts=gen_tts,
        dry_run=args.dry_run,
    )
    print()
    conn.close()
