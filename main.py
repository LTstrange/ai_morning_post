"""拉取 RSS、同步用户、智能筛选文章、生成 AI 早报和语音。"""

import argparse

from commands import cmd_fetch, cmd_sync, cmd_parse, cmd_generate, cmd_history, cmd_run


def main():
    parser = argparse.ArgumentParser(description="拉取 RSS、同步用户、生成 AI 早报")
    subparsers = parser.add_subparsers(dest="command", help="可用子命令")

    # fetch 子命令
    fetch_parser = subparsers.add_parser("fetch", help="拉取 RSS 原始内容")
    fetch_parser.add_argument(
        "-f", "--force", action="store_true", help="忽略缓存，强制重新拉取"
    )

    # sync 子命令
    subparsers.add_parser("sync", help="同步用户与订阅")

    # parse 子命令
    subparsers.add_parser("parse", help="解析并存储文章")

    # generate 子命令
    generate_parser = subparsers.add_parser("generate", help="生成早报内容")
    generate_parser.add_argument("-u", "--user", help="只为指定用户名生成早报")
    generate_parser.add_argument(
        "--report", action="store_true", help="生成 Markdown 早报"
    )
    generate_parser.add_argument("--voice", action="store_true", help="生成语音播报稿")
    generate_parser.add_argument(
        "--tts", action="store_true", help="生成语音音频（需要 MIMO_API_KEY）"
    )
    generate_parser.add_argument(
        "--dry-run", action="store_true", help="模拟运行，不标记文章为已推送"
    )

    # history 子命令
    history_parser = subparsers.add_parser("history", help="管理推送历史")
    history_subparsers = history_parser.add_subparsers(
        dest="history_action", help="历史操作"
    )

    # history show
    history_show_parser = history_subparsers.add_parser("show", help="查看推送历史")
    history_show_parser.add_argument(
        "username", nargs="?", help="指定用户名（留空查看所有）"
    )
    history_show_parser.add_argument("--batch", type=int, help="按批次 ID 筛选")
    history_show_parser.add_argument("--date", help="按日期筛选（YYYY-MM-DD）")
    history_show_parser.add_argument(
        "--from", dest="date_from", help="起始日期（YYYY-MM-DD）"
    )
    history_show_parser.add_argument(
        "--to", dest="date_to", help="结束日期（YYYY-MM-DD）"
    )

    # history reset
    history_reset_parser = history_subparsers.add_parser("reset", help="重置推送历史")
    history_reset_parser.add_argument(
        "username", nargs="?", help="指定用户名（留空重置所有）"
    )
    history_reset_parser.add_argument("--batch", type=int, help="按批次 ID 重置")
    history_reset_parser.add_argument("--date", help="按日期重置（YYYY-MM-DD）")
    history_reset_parser.add_argument(
        "--after", help="重置该日期之后的记录（不含当天，YYYY-MM-DD）"
    )

    # history batches
    history_batches_parser = history_subparsers.add_parser(
        "batches", help="查看推送批次列表"
    )
    history_batches_parser.add_argument(
        "username", nargs="?", help="指定用户名（留空查看所有）"
    )

    # run 子命令
    run_parser = subparsers.add_parser(
        "run", help="执行完整流程（fetch + sync + parse + generate）"
    )
    run_parser.add_argument("-u", "--user", help="只为指定用户名生成早报")
    run_parser.add_argument("--report", action="store_true", help="生成 Markdown 早报")
    run_parser.add_argument("--voice", action="store_true", help="生成语音播报稿")
    run_parser.add_argument(
        "--tts", action="store_true", help="生成语音音频（需要 MIMO_API_KEY）"
    )
    run_parser.add_argument(
        "--dry-run", action="store_true", help="模拟运行，不标记文章为已推送"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 根据子命令调用相应的处理函数
    if args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "parse":
        cmd_parse(args)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "history":
        if not args.history_action:
            history_parser.print_help()
            return
        cmd_history(args)
    elif args.command == "run":
        cmd_run(args)


if __name__ == "__main__":
    main()
