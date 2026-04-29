"""子命令处理模块。"""

from db import reset_user_history, get_user_history
from rss import fetch_and_store_raw_feeds, parse_and_store_articles
from users import init_connection, sync_users, generate_for_users


def cmd_fetch(args):
    """处理 fetch 子命令。"""
    conn = init_connection()
    print("=== 拉取并存储 RSS 原始内容 ===")
    fetch_and_store_raw_feeds(conn)
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
        dry_run=args.dry_run
    )
    conn.close()


def cmd_history(args):
    """处理 history 子命令。"""
    conn = init_connection()
    
    if args.history_action == "show":
        if args.username:
            user = conn.execute(
                "SELECT id FROM users WHERE name = ?", (args.username,)
            ).fetchone()
            if not user:
                print(f'未找到用户 "{args.username}"')
                conn.close()
                return
            print(f"=== {args.username} 的推送历史 ===")
            history = get_user_history(conn, user["id"])
        else:
            print("=== 所有用户推送历史 ===")
            history = get_user_history(conn)

        if not history:
            print("暂无推送记录")
        else:
            for h in history:
                print(f"  [{h['user_name']}] {h['title']} ({h['pushed_at']})")
    
    elif args.history_action == "reset":
        if args.username:
            user = conn.execute(
                "SELECT id FROM users WHERE name = ?", (args.username,)
            ).fetchone()
            if not user:
                print(f'未找到用户 "{args.username}"')
                conn.close()
                return
            reset_user_history(conn, user["id"])
            print(f"已重置 {args.username} 的推送历史")
        else:
            reset_user_history(conn)
            print("已重置所有用户的推送历史")
    
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
        dry_run=args.dry_run
    )
    print()
    conn.close()