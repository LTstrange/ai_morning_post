# AGENTS.md

## Setup
- Package manager: **uv** (not pip/poetry)
- Python 3.14 required (see `.python-version`)
- Install deps: `uv sync`

## Run
```
# 子命令用法
uv run python main.py fetch      # 从 URL 拉取 RSS 存入数据库（24 小时内缓存有效则跳过）
uv run python main.py sync       # 同步用户与订阅
uv run python main.py parse      # 解析并存储文章
uv run python main.py generate   # 生成早报内容（默认生成报告和语音稿）
uv run python main.py run        # 执行完整流程（fetch + sync + parse + generate）

# 生成选项
uv run python main.py generate --report        # 只生成 Markdown 早报
uv run python main.py generate --voice         # 只生成语音播报稿
uv run python main.py generate --tts           # 生成语音音频（需要 MIMO_API_KEY）
uv run python main.py generate --dry-run       # 模拟运行，不标记文章为已推送
uv run python main.py generate -u Alice        # 只为 Alice 生成早报

# 历史管理
uv run python main.py history show             # 查看所有用户的推送历史
uv run python main.py history show Alice       # 查看 Alice 的推送历史
uv run python main.py history reset            # 重置所有用户的推送历史
uv run python main.py history reset Alice      # 重置 Alice 的推送历史

# 批量生成语音音频
uv run python tts.py             # 批量生成 reports/ 目录下所有语音播报稿的音频
```

## Project structure
- `main.py` — 入口；参数解析和子命令分发
- `commands.py` — 子命令处理模块；每个子命令的处理函数
- `rss.py` — RSS 数据层；拉取、解析、存储 RSS 数据
- `users.py` — 用户业务层；用户订阅管理和早报生成
- `generate_report.py` — AI 早报生成模块；智能筛选候选文章，调用 DeepSeek API 生成 Markdown 早报和语音播报稿
  - 可被其他脚本导入（导入不触发副作用）
  - 公开函数：`fetch_candidate_articles()`, `select_articles()`, `build_user_prompt()`, `generate_report()`, `generate_voice_script()`, `call_llm()`
- `tts.py` — 语音合成模块；调用小米 MiMo-V2.5-TTS API 将播报稿转为音频
  - 可作为脚本运行：`uv run python tts.py` 批量生成所有语音播报稿的音频
  - 公开函数：`text_to_speech(text, output_path, voice, style_instruction)`
  - 默认语音：冰糖（中文女声）
- `db.py` — SQLite 数据库模块（init_db, ensure_feed, get_latest_raw_feed, save_raw_feed, save_article, ensure_user, ensure_subscription, mark_article_pushed, reset_user_history, get_user_history）
- `feeds.json` — feed 源配置（name + url）
- `users.json` — 用户与订阅配置（name + subscriptions，subscriptions 用期刊名匹配 feeds 表）
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
- 六张表：
  - `feeds` — RSS 源信息（name, url）
  - `raw_feeds` — 每次拉取的原始 XML（SHA-256 去重）
  - `articles` — 解析后的文章（link UNIQUE 去重，published 为 ISO 8601 格式，authors 为 JSON 数组）
  - `users` — 用户（name UNIQUE）
  - `subscriptions` — 用户与 feed 的多对多订阅关系（UNIQUE(user_id, feed_id)）
  - `user_article_history` — 用户推送历史（UNIQUE(user_id, article_id)）
- 结构定义在 `db.py` 的 `init_db()` 中，后续改表直接改这个函数
- 不使用迁移框架；改表后删除 `data.db` 重新运行即可重建

## Adding a new feed
1. 在 `feeds.json` 的 `feeds` 数组中添加 `{"name": "...", "url": "..."}`
2. 运行 `uv run python main.py fetch`

## Conventions
- Code comments and docstrings are in Chinese (Mandarin)
- No tests, linter, or formatter configured yet

## Gotchas
- IEEE 会对默认 User-Agent 返回 418，下载时需伪装浏览器 UA（已在代码中处理）
- `pandas` and `pydantic` are declared as dependencies but not yet used in code
