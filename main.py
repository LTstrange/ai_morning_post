"""拉取 RSS、同步用户、智能筛选文章、生成 AI 早报和语音。"""

import argparse

from commands import (
    cmd_backfill,
    cmd_export,
    cmd_fetch,
    cmd_parse,
    cmd_regen,
    cmd_history,
    cmd_run,
    cmd_migrate,
    cmd_user,
)


def main():
    parser = argparse.ArgumentParser(description="拉取 RSS、同步用户、生成 AI 早报")
    subparsers = parser.add_subparsers(dest="command", help="可用子命令")

    # fetch 子命令
    fetch_parser = subparsers.add_parser("fetch", help="拉取 RSS 原始内容")
    fetch_parser.add_argument(
        "-f", "--force", action="store_true", help="忽略缓存，强制重新拉取"
    )

    # parse 子命令
    parse_parser = subparsers.add_parser("parse", help="解析并存储文章")
    parse_parser.add_argument(
        "--enrich", action="store_true",
        help="为已有的空摘要文章通过 CrossRef DOI 补全",
    )

    # regen 子命令
    regen_parser = subparsers.add_parser("regen", help="基于已有批次重新生成产物")
    regen_parser.add_argument("batch", type=int, help="批次 ID")
    regen_parser.add_argument(
        "--report", action="store_true", help="生成 Markdown 早报"
    )
    regen_parser.add_argument("--voice", action="store_true", help="生成语音播报稿")
    regen_parser.add_argument(
        "--tts", action="store_true", help="生成语音音频（需要 MIMO_API_KEY）"
    )
    regen_parser.add_argument(
        "--all", action="store_true", help="生成早报、语音稿和语音音频"
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
    history_show_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="显示条数（默认 10，0 表示不限）",
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

    # user 子命令
    user_parser = subparsers.add_parser("user", help="管理用户与订阅")
    user_subparsers = user_parser.add_subparsers(dest="user_action", help="用户操作")

    # user add
    user_add_parser = user_subparsers.add_parser("add", help="添加用户")
    user_add_parser.add_argument("username", help="用户名")

    # user remove
    user_remove_parser = user_subparsers.add_parser("remove", help="硬删除用户")
    user_remove_parser.add_argument("username", help="用户名")

    # user deactivate
    user_deactivate_parser = user_subparsers.add_parser("deactivate", help="停用用户")
    user_deactivate_parser.add_argument("username", help="用户名")

    # user activate
    user_activate_parser = user_subparsers.add_parser("activate", help="激活用户")
    user_activate_parser.add_argument("username", help="用户名")

    # user rename
    user_rename_parser = user_subparsers.add_parser("rename", help="重命名用户")
    user_rename_parser.add_argument("username", help="当前用户名")
    user_rename_parser.add_argument("new_name", help="新用户名")

    # user list
    user_subparsers.add_parser("list", help="列出所有用户")

    # user show
    user_show_parser = user_subparsers.add_parser("show", help="查看用户详情")
    user_show_parser.add_argument("username", help="用户名")

    # user subscribe
    user_subscribe_parser = user_subparsers.add_parser("subscribe", help="添加订阅")
    user_subscribe_parser.add_argument("username", help="用户名")
    user_subscribe_parser.add_argument("feed_name", help="期刊名称")

    # user unsubscribe
    user_unsubscribe_parser = user_subparsers.add_parser("unsubscribe", help="取消订阅")
    user_unsubscribe_parser.add_argument("username", help="用户名")
    user_unsubscribe_parser.add_argument("feed_name", help="期刊名称")

    # user sync
    user_sync_parser = user_subparsers.add_parser("sync", help="从文件增量导入")
    user_sync_parser.add_argument(
        "file", nargs="?", default="users.json", help="配置文件路径（默认 users.json）"
    )

    # user restore
    user_restore_parser = user_subparsers.add_parser("restore", help="从文件覆盖导入")
    user_restore_parser.add_argument("file", help="配置文件路径")

    # user export
    user_export_parser = user_subparsers.add_parser("export", help="导出用户配置到文件")
    user_export_parser.add_argument("file", help="输出文件路径")

    # export 子命令
    export_parser = subparsers.add_parser("export", help="从数据库导出批次产物到文件")
    export_parser.add_argument("batch", type=int, help="批次 ID")
    export_parser.add_argument(
        "--report", action="store_true", help="只导出早报"
    )
    export_parser.add_argument(
        "--voice", action="store_true", help="只导出语音稿"
    )
    export_parser.add_argument(
        "--tts", action="store_true", help="只导出音频"
    )
    export_parser.add_argument(
        "-o", "--output-dir", default=".", help="输出目录（默认当前目录）"
    )

    # backfill 子命令
    backfill_parser = subparsers.add_parser(
        "backfill", help="为缺少 embedding 的文章批量计算向量"
    )
    backfill_parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="每批处理文章数（默认 100）",
    )

    # migrate 子命令
    subparsers.add_parser("migrate", help="执行所有未应用的数据库迁移")

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
        "--all", action="store_true", help="生成早报、语音稿和语音音频"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 根据子命令调用相应的处理函数
    if args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "parse":
        cmd_parse(args)
    elif args.command == "regen":
        cmd_regen(args)
    elif args.command == "history":
        if not args.history_action:
            history_parser.print_help()
            return
        cmd_history(args)
    elif args.command == "user":
        if not args.user_action:
            user_parser.print_help()
            return
        cmd_user(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "backfill":
        cmd_backfill(args)
    elif args.command == "migrate":
        cmd_migrate(args)
    elif args.command == "run":
        cmd_run(args)


if __name__ == "__main__":
    main()
