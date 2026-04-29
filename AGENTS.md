# AGENTS.md

## Setup
- Package manager: **uv** (not pip/poetry)
- Python 3.14 required (see `.python-version`)
- Install deps: `uv sync`

## Run
```
# 子命令用法
uv run python main.py fetch      # 从 URL 拉取 RSS 存入数据库（23 小时内缓存有效则跳过）
uv run python main.py parse      # 解析并存储文章
uv run python main.py run        # 执行完整流程（fetch + sync + parse + 选文 + 生成）

# run 选项
uv run python main.py run -u Alice             # 只为 Alice 执行
uv run python main.py run --report             # 只生成 Markdown 早报
uv run python main.py run --voice              # 只生成语音播报稿
uv run python main.py run --tts                # 生成语音音频（需要 MIMO_API_KEY）
uv run python main.py run --dry-run            # 模拟运行，不标记文章为已推送

# 用户管理
uv run python main.py user add Alice           # 添加用户（已存在则跳过）
uv run python main.py user remove Alice        # 硬删除用户（级联删除全部数据）
uv run python main.py user deactivate Alice    # 停用用户（保留数据）
uv run python main.py user activate Alice      # 激活用户
uv run python main.py user list                # 列出所有用户
uv run python main.py user show Alice          # 查看用户详情和订阅
uv run python main.py user subscribe Alice "IEEE TMM"    # 添加订阅
uv run python main.py user unsubscribe Alice "IEEE TMM"  # 取消订阅
uv run python main.py user sync                # 增量导入（默认 users.json）
uv run python main.py user sync custom.json    # 从指定文件增量导入
uv run python main.py user restore file.json   # 覆盖导入（按人覆盖订阅 + 激活用户）
uv run python main.py user export out.json      # 导出现有用户到文件

# 基于已有批次重新生成（跳过选文流程）
uv run python main.py regen 5                  # 用批次 #5 的数据生成早报+语音稿
uv run python main.py regen 5 --voice          # 用批次 #5 的早报生成语音稿
uv run python main.py regen 5 --report         # 重新生成早报（语音稿自动失效）
uv run python main.py regen 5 --tts            # 用批次 #5 的语音稿生成音频

# 历史管理
uv run python main.py history show             # 查看所有用户的推送历史
uv run python main.py history show Alice       # 查看 Alice 的推送历史
uv run python main.py history show --batch 3   # 查看批次 #3 的推送记录
uv run python main.py history show --date 2026-04-29       # 按日期查看
uv run python main.py history show --from 2026-04-20 --to 2026-04-29  # 按日期范围查看
uv run python main.py history batches          # 查看所有推送批次
uv run python main.py history batches Alice    # 查看 Alice 的推送批次
uv run python main.py history reset            # 重置所有用户的推送历史
uv run python main.py history reset Alice      # 重置 Alice 的推送历史
uv run python main.py history reset --batch 3  # 回滚批次 #3（级联删除）
uv run python main.py history reset --date 2026-04-29      # 重置指定日期的记录
uv run python main.py history reset --after 2026-04-20     # 重置该日期之后的记录（不含当天）

# 批量生成语音音频
uv run python tts.py             # 批量生成 reports/ 目录下所有语音播报稿的音频

# 数据库迁移
uv run python main.py migrate    # 执行所有未应用的数据库迁移
uv run python migrate.py         # 同上（独立入口）
```

## Project structure
- `main.py` — 入口；参数解析和子命令分发
- `commands.py` — 子命令处理模块；每个子命令的处理函数
- `rss.py` — RSS 数据层；拉取、解析、存储 RSS 数据
- `users.py` — 用户业务层；用户订阅管理和早报生成
- `generate_report.py` — AI 早报生成模块；智能筛选候选文章，调用 DeepSeek API 生成 Markdown 早报和语音播报稿
  - 可被其他脚本导入（导入不触发副作用）
  - 公开函数：`fetch_candidate_articles()`, `select_articles()`, `build_user_prompt()`, `generate_report()`, `generate_voice_script(report, user_prompt)`, `call_llm()`
  - `generate_voice_script` 依赖早报文本和原始论文数据，语音稿是对早报的讲解
- `tts.py` — 语音合成模块；调用小米 MiMo-V2.5-TTS API 将播报稿转为音频
  - 可作为脚本运行：`uv run python tts.py` 批量生成所有语音播报稿的音频
  - 公开函数：`text_to_speech(text, output_path, voice, style_instruction)`
  - 默认语音：冰糖（中文女声）
- `db.py` — SQLite 数据库模块（init_db, ensure_feed, get_latest_raw_feed, save_raw_feed, save_article, ensure_user, ensure_subscription, create_push_batch, mark_article_pushed, reset_user_history, get_user_history, get_push_batches, get_batch, get_batch_articles, update_batch_report, update_batch_voice, update_batch_tts, migrate）
- `migrate.py` — 独立迁移入口脚本；调用 db.migrate() 执行所有未应用的迁移
- `migrations/` — SQL 迁移文件目录（按 `NNN_description.sql` 命名，如 `001_initial.sql`）
- `feeds.json` — feed 源配置（name + url）
- `users.json` — 用户与订阅配置（name + subscriptions + interests，interests 用于辅助 AI 筛选文章）
- `.env` — 环境变量（`DEEPSEEK_API_KEY`、`MIMO_API_KEY`，已加入 .gitignore）
- `prompts/` — LLM 提示词文件（`report_system.txt` 和 `voice_system.txt` 和 `select_system.txt`，修改提示词只需编辑这三个文件）
- `reports/` — 生成的早报输出目录（`YYYY-MM-DD.md` + `YYYY-MM-DD-voice.txt` + `YYYY-MM-DD-voice.wav`，已加入 .gitignore）
- `data.db` — SQLite 数据库文件（已加入 .gitignore）

### 依赖关系
```
main.py
  └── commands.py
        ├── rss.py
        └── users.py
              ├── generate_report.py
              ├── tts.py
              └── db.py
```

## Database
- 八张表（含迁移版本表）：
  - `feeds` — RSS 源信息（name, url）
  - `raw_feeds` — 每次拉取的原始 XML（SHA-256 去重）
  - `articles` — 解析后的文章（link UNIQUE 去重，published 为 ISO 8601 格式，authors 为 JSON 数组）
  - `users` — 用户（name UNIQUE, active BOOLEAN, interests TEXT）
  - `subscriptions` — 用户与 feed 的多对多订阅关系（UNIQUE(user_id, feed_id)）
  - `push_batches` — 推送批次（user_id, created_at, report, voice_script, tts_audio_path），每次 run 为每个用户创建一个批次
  - `user_article_history` — 用户推送历史（batch_id 外键 ON DELETE CASCADE，UNIQUE(user_id, article_id)）
  - `schema_version` — 迁移版本追踪表（version, applied_at）
- 使用基于文件的迁移系统：`migrations/` 目录下的 `NNN_description.sql` 文件按版本号顺序执行
- `db.migrate(conn)` 执行所有未应用的迁移；`db.init_db()` 内部调用 `migrate()`
- 存量数据库兼容：首次运行 migrate 时，若 `feeds` 表已存在但 `schema_version` 为空，自动标记版本 1，避免重复执行初始迁移
- 不使用迁移框架；迁移文件手工编写
- **不要** 修改已有迁移文件，只新增

## Adding a new migration
1. 在 `migrations/` 目录下新建文件，如 `002_add_user_active.sql`
2. 文件名格式：`NNN_description.sql`，NNN 为递增三位数版本号
3. 运行 `uv run python main.py migrate` 应用迁移

## Adding a new feed
1. 在 `feeds.json` 的 `feeds` 数组中添加 `{"name": "...", "url": "..."}`
2. 运行 `uv run python main.py fetch`

## Conventions
- Code comments and docstrings are in Chinese (Mandarin)
- No tests, linter, or formatter configured yet

## Gotchas
- IEEE 会对默认 User-Agent 返回 418，下载时需伪装浏览器 UA（已在代码中处理）
- `pandas` and `pydantic` are declared as dependencies but not yet used in code
