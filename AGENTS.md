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
uv run python main.py run --all                # 生成早报、语音稿和语音音频
uv run python main.py run --email              # 生成后发送邮件给用户
uv run python main.py run --all --email        # 生成全部产物并发送邮件

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
uv run python main.py regen 5 --all            # 重新生成早报、语音稿和音频

# 历史管理
uv run python main.py history show             # 查看最近 10 条推送历史（按时间倒序）
uv run python main.py history show --limit 0   # 查看全部推送历史
uv run python main.py history show --limit 20  # 查看最近 20 条
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

# Embedding 回填（首次升级或存量文章补向量）
uv run python main.py backfill               # 为所有缺少 embedding 的文章计算向量
uv run python main.py backfill --batch-size 50  # 每批处理 50 篇

# 发送已有批次的邮件（不重新生成）
uv run python main.py send 5                   # 发送批次 #5 的早报邮件
uv run python main.py send 5 --tts             # 附带 TTS 音频附件

# 导出批次产物
uv run python main.py export 5                  # 导出批次 #5 的所有产物到当前目录
uv run python main.py export 5 --report         # 只导出早报
uv run python main.py export 5 --voice          # 只导出语音稿
uv run python main.py export 5 --tts            # 只导出音频
uv run python main.py export 5 -o ./out         # 指定输出目录

# 数据库迁移
uv run python main.py migrate    # 执行所有未应用的数据库迁移
uv run python migrate.py         # 同上（独立入口）
```

## Project structure
- `main.py` — 入口；参数解析和子命令分发
- `commands.py` — 子命令处理模块；每个子命令的处理函数
- `rss.py` — RSS 数据层；拉取、解析、存储 RSS 数据；解析时自动提取 DOI，摘要为空时通过 CrossRef API 补全
  - 按出版商分组解析：每个出版商一个 `_parse_entry_xxx(entry)` 函数，通过 `ENTRY_PARSERS` 字典分发
  - `ENTRY_PARSERS` 每项包含 `parser`（解析函数）和 `enrich_abstract`（是否需要 CrossRef 补全）
  - 未知出版商会报错并跳过，不影响已适配出版商
- `abstract_fetcher.py` — DOI 摘要补全模块；调用 CrossRef API 按 DOI 查询摘要
  - 公开函数：`fetch_abstract_by_doi(doi) -> str | None`
  - 自动剥离 JATS XML 标签，返回纯文本
  - 限流 1 req/s；可通过 `.env` 中 `CROSSREF_MAILTO` 进入 polite pool
- `mailer.py` — 邮件发送模块；通过 SMTP 发送 HTML 早报邮件，支持 TTS 音频附件
  - 公开函数：`send_report_email(to_addr, subject, report_md, tts_path=None)`、`markdown_to_html(md_text)`
  - 使用 `smtplib.SMTP_SSL`（适配 QQ 邮箱 465 端口）
  - 环境变量：`SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`
- `users.py` — 用户业务层；用户订阅管理和早报生成
- `generate_report.py` — AI 早报生成模块；智能筛选候选文章，调用 DeepSeek API 生成 Markdown 早报和语音播报稿
  - 可被其他脚本导入（导入不触发副作用）
  - 公开函数：`fetch_candidate_articles()`, `select_articles()`, `build_user_prompt()`, `generate_report()`, `generate_voice_script(report, user_prompt)`, `call_llm()`
  - `generate_voice_script` 依赖早报文本和原始论文数据，语音稿是对早报的讲解
  - 早报和语音稿内容只存储在数据库中（`push_batches.report` 和 `push_batches.voice_script`），不写入磁盘文件
  - 使用 `export` 子命令从数据库导出到文件
- `tts.py` — 语音合成模块；调用小米 MiMo-V2.5-TTS API 将播报稿转为 MP3 音频
  - 公开函数：`text_to_speech(text, voice, style_instruction) -> Path | None`
  - 音频以 content-addressable 方式存储在 `audio/` 目录（SHA-256 hash 前 2 字符为子目录）
  - 默认语音：冰糖（中文女声）
- `embedding.py` — 文章语义嵌入模块；懒加载 sentence-transformers 模型，计算/序列化/反序列化向量，语义检索
  - 模型：`paraphrase-multilingual-MiniLM-L12-v2`（384维，支持中英跨语言检索）
  - 公开函数：`compute_embedding(text)`, `deserialize_embedding(blob)`, `semantic_search(query_text, articles, top_k)`
  - 模型懒加载：首次调用时才下载和加载，不影响不需要 embedding 的命令
- `db.py` — SQLite 数据库模块（init_db, ensure_feed, get_latest_raw_feed, save_raw_feed, save_article, ensure_user, ensure_subscription, create_push_batch, mark_article_pushed, reset_user_history, get_user_history, get_push_batches, get_batch, get_batch_articles, update_batch_report, update_batch_voice, update_batch_tts, migrate, get_unpushed_articles_with_embeddings, get_articles_without_embedding, update_article_embedding, batch_update_embeddings, set_user_email）
- `migrate.py` — 独立迁移入口脚本；调用 db.migrate() 执行所有未应用的迁移
- `migrations/` — SQL 迁移文件目录（按 `NNN_description.sql` 命名，如 `001_initial.sql`）
- `feeds.json` — feed 源配置（按出版商分组：publishers → {publisher_key → {feeds: [{name, url}]}}）
- `users.json` — 用户与订阅配置（name + email + subscriptions + interests，interests 用于辅助 AI 筛选文章）
- `.env` — 环境变量（`DEEPSEEK_API_KEY`、`MIMO_API_KEY`、`CROSSREF_MAILTO`、`SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`，已加入 .gitignore）
- `prompts/` — LLM 提示词文件（`report_system.txt` 和 `voice_system.txt` 和 `select_system.txt`，修改提示词只需编辑这三个文件）
- `audio/` — TTS 音频存储目录（content-addressable，`{hash[:2]}/{hash[2:]}.mp3`，已加入 .gitignore）
- `data.db` — SQLite 数据库文件（已加入 .gitignore）

### 依赖关系
```
main.py
  └── commands.py
        ├── rss.py
        │     └── abstract_fetcher.py
        └── users.py
              ├── generate_report.py
              ├── tts.py
              ├── mailer.py
              └── db.py
```

## Database
- 八张表（含迁移版本表）：
  - `feeds` — RSS 源信息（name, url, publisher）
  - `raw_feeds` — 每次拉取的原始 XML（SHA-256 去重）
  - `articles` — 解析后的文章（link UNIQUE 去重，published 为 ISO 8601 格式，authors 为 JSON 数组，doi TEXT 存储 DOI，embedding BLOB 存储 384 维 float32 向量）
  - `users` — 用户（name UNIQUE, active BOOLEAN, interests TEXT, email TEXT）
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
1. 在 `feeds.json` 对应出版商的 `feeds` 数组中添加 `{"name": "...", "url": "..."}`
2. 运行 `uv run python main.py fetch`

## Adding a new publisher
1. 在 `feeds.json` 的 `publishers` 下新增出版商分组，添加该出版商的 feeds
2. 在 `rss.py` 中编写 `_parse_entry_xxx(entry)` 解析函数，处理该出版商 RSS 的特殊格式（日期字段、摘要、作者等）
3. 将解析函数注册到 `ENTRY_PARSERS` 字典
4. 若该出版商 RSS 不提供摘要，解析函数中将 `summary` 设为 `None`，并在 `ENTRY_PARSERS` 中设置 `"enrich_abstract": True`，由 CrossRef API 自动通过 DOI 补全
5. 若该出版商 RSS 不提供作者，在 `ENTRY_PARSERS` 中设置 `"enrich_authors": True`，由 CrossRef API 自动通过 DOI 补全
6. `parse_and_store_articles` 会对同一篇文章只调用一次 CrossRef API 同时补全摘要和作者

### 已知不支持的期刊
- **Elsevier (ScienceDirect)** 旗下期刊：RSS 不提供摘要、DOI、独立作者和日期字段（全部嵌在 description HTML 中），且 Elsevier 不向 CrossRef 上传摘要，无法通过 DOI 补全
- **Neurology**（Wolters Kluwer）：RSS 为 RDF 1.0 格式，不提供摘要，且 Wolters Kluwer 不向 CrossRef 提交摘要；`dc:creator` 字段将作者名和单位混在一起无法解析
- **Medicine**（LWW / Wolters Kluwer）：RSS 数据完整（有摘要、作者、DOI），但被 Cloudflare 保护，程序无法自动拉取
- **Nature**：最新文章 DOI 注册到 CrossRef 有较大延迟，无法及时获取完整摘要

注意：同一出版商旗下不同期刊的 RSS 格式和数据完整度可能不同，需逐个验证

## Conventions
- Code comments and docstrings are in Chinese (Mandarin)
- No tests, linter, or formatter configured yet

## Gotchas
- IEEE 会对默认 User-Agent 返回 418，下载时需伪装浏览器 UA（已在代码中处理）
- `pandas` and `pydantic` are declared as dependencies but not yet used in code
