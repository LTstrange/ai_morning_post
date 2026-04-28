# AGENTS.md

## Setup
- Package manager: **uv** (not pip/poetry)
- Python 3.14 required (see `.python-version`)
- Install deps: `uv sync`

## Run
```
uv run python main.py            # 拉取 RSS、同步用户、解析文章入库
uv run python generate_report.py  # 生成 AI 早报（Markdown + 语音稿）
```

## Project structure
- `main.py` — entrypoint；三步流程：1) 读取本地 XML 存入 raw_feeds 表 2) 同步用户与订阅 3) 从 raw_feeds 解析文章存入 articles 表
- `generate_report.py` — AI 早报生成模块；从 articles 表读取最近一天的论文，调用 DeepSeek API 生成 Markdown 早报和语音播报稿
  - 可作为脚本直接运行，也可被其他脚本导入（导入不触发副作用）
  - 公开函数：`fetch_latest_articles()`, `build_user_prompt()`, `generate_report()`, `generate_voice_script()`, `call_llm()`
- `db.py` — SQLite 数据库模块（init_db, ensure_feed, save_raw_feed, save_article, ensure_user, ensure_subscription）
- `feeds.json` — feed 源配置（name + url）
- `users.json` — 用户与订阅配置（name + subscriptions，subscriptions 用期刊名匹配 feeds 表）
- `.env` — 环境变量（`DEEPSEEK_API_KEY`，已加入 .gitignore）
- `output/` — 本地 RSS XML 缓存（本地有则直接读取，无则自动从 URL 下载；已加入 .gitignore）
- `prompts/` — LLM 提示词文件（`report_system.txt` 和 `voice_system.txt`，修改提示词只需编辑这两个文件）
- `reports/` — 生成的早报输出目录（`YYYY-MM-DD.md` + `YYYY-MM-DD-voice.txt`，已加入 .gitignore）
- `data.db` — SQLite 数据库文件（已加入 .gitignore）

## Database
- 五张表：
  - `feeds` — RSS 源信息（name, url）
  - `raw_feeds` — 每次拉取的原始 XML（SHA-256 去重）
  - `articles` — 解析后的文章（link UNIQUE 去重，published 为 ISO 8601 格式，authors 为 JSON 数组）
  - `users` — 用户（name UNIQUE）
  - `subscriptions` — 用户与 feed 的多对多订阅关系（UNIQUE(user_id, feed_id)）
- 结构定义在 `db.py` 的 `init_db()` 中，后续改表直接改这个函数
- 不使用迁移框架；改表后删除 `data.db` 重新运行即可重建（原始数据从 `output/` 重新导入）

## Adding a new feed
1. 在 `feeds.json` 的 `feeds` 数组中添加 `{"name": "...", "url": "..."}`
2. 手动下载对应 XML 到 `output/`（文件名需与 URL 中的 TOC 编号匹配，如 `TOC1234.xml`）
3. 运行 `uv run python main.py`

如果不手动下载，程序会自动从 URL 拉取并保存到 `output/`。

## Conventions
- Code comments and docstrings are in Chinese (Mandarin)
- No tests, linter, or formatter configured yet

## Gotchas
- IEEE 会对默认 User-Agent 返回 418，下载时需伪装浏览器 UA（已在代码中处理）
- `pandas` and `pydantic` are declared as dependencies but not yet used in code
- `generate_report.py` 的 `load_dotenv()` 仅在 `main()` 中调用，导入时不会触发副作用

