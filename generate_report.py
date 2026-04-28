"""从数据库读取最近一天的论文，调用 DeepSeek 生成中文早报，输出为 Markdown 文件。"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from db import get_connection

REPORTS_DIR = Path(__file__).parent / "reports"

REPORT_SYSTEM_PROMPT = """\
你是一个学术论文早报编辑。用户会提供一批当天出版的论文信息（标题、摘要、作者、链接、所属期刊）。
请根据这些信息生成一份中文早报，要求：
1. 用一级标题写日期，如 "# AI 早报 - (对应日期，如：2026-04-27)"
2. 按期刊分组，用二级标题标注期刊名
3. 每篇论文包含：
   - 中文翻译的标题（三级标题）
   - 2-3 个关键要点（bullet points，简洁专业）
   - 原文链接
4. 在早报最开头写一段 3-5 句的今日总览，概括当天论文的主要方向和亮点
5. 直接输出 Markdown 格式，不要输出任何多余的解释
"""

VOICE_SYSTEM_PROMPT = """\
你是一个学术播报主持人，生成的文本将直接送入 TTS 引擎朗读。
用户会提供一批当天出版的论文信息（标题、摘要、作者、所属期刊）。
请根据这些信息撰写一段中文语音播报稿。

## 播报稿要求
1. 总字数控制在 400-500 字（约 2 分钟朗读时长）
2. 口语化、自然流畅，适合直接朗读，就像播客或早间新闻播报
3. 开头用一句简短的问候引入，如"大家好，欢迎收听今天的学术早报"
4. 概括当天论文的整体方向，然后逐篇简要介绍核心贡献，不需要过于详细
5. 结尾用一句话收束

## TTS 发音规则（必须严格遵守）
- 首字母缩写词根据实际读法改写：
  - 通常作为单词朗读的（如 NASA、NATO），保持原样
  - 有特殊读法的，用文字写出：IEEE → "I triple E"，C++ → "C plus plus"
- 含数字的缩写：3D → "三维"
- 含符号的内容：@ → "at"，# → "井号"，& → "和"
- 数字根据语境决定读法：年份 2024 → "二零二四"，数量 3500 → "三千五百"
- 百分数用文字表达：15% → "百分之十五"
- 中文拼音姓名直接还原为中文汉字
- 不要包含任何 Markdown 格式符号、链接、括号标注等不适合朗读的内容

## 输出要求
- 只输出最终可直接朗读的文本，不要输出标题、解释或额外说明
- 稿子里写什么，TTS 就读什么，不能有任何需要跳过的内容
- 可以用英文中括号`[]`标注语气和表现

## TTS示例
- [紧张，深呼吸]呼……冷静，冷静。不就是一个面试吗……[语速加快，碎碎念]自我介绍已经背了五十遍了，应该没问题的。加油，你可以的……[小声]哎呀，领带歪没歪？
- [极其疲惫，有气无力]师傅……到地方了叫我一声……[长叹一口气]我先眯一会儿，这班加得我魂儿都要散了。
- Achoo! Ahem. I—I really [cough] think I am coming down with a terrible [cough] terrible cold.
- [提高音量喊话]大姐！这鱼新鲜着呢！早上刚捞上来的！哎！那个谁，别乱翻，压坏了你赔啊？！
- 我已经很久，一个 long long long long time，没有跟朋友有过非工作或者学习方面的话题讨论了。
"""


def fetch_latest_articles():
    """查询数据库中最近一天出版的所有论文。"""
    conn = get_connection()

    row = conn.execute(
        "SELECT MAX(substr(published, 1, 10)) AS latest_date FROM articles"
    ).fetchone()
    latest_date = row["latest_date"]

    if not latest_date:
        conn.close()
        return None, []

    rows = conn.execute(
        "SELECT a.title, a.authors, a.link, a.summary, a.published, f.name AS feed_name "
        "FROM articles a JOIN feeds f ON a.feed_id = f.id "
        "WHERE substr(a.published, 1, 10) = ? "
        "ORDER BY f.name, a.id",
        (latest_date,),
    ).fetchall()

    conn.close()
    return latest_date, rows


def build_user_prompt(latest_date, articles):
    """将论文列表组装为发给 LLM 的用户 prompt。"""
    lines = [f"今天的日期是 {latest_date}，以下是今天出版的 {len(articles)} 篇论文：\n"]

    for i, a in enumerate(articles, 1):
        authors = ", ".join(json.loads(a["authors"]))
        lines.append(f"--- 论文 {i} ---")
        lines.append(f"期刊: {a['feed_name']}")
        lines.append(f"标题: {a['title']}")
        lines.append(f"作者: {authors}")
        lines.append(f"链接: {a['link']}")
        lines.append(f"摘要: {a['summary']}")
        lines.append("")

    return "\n".join(lines)


def call_llm(system_prompt, user_prompt):
    """调用 DeepSeek API，返回生成的文本。"""
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )

    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        reasoning_effort="high",
    )

    return response.choices[0].message.content


def generate_report(user_prompt):
    """调用 LLM 生成 Markdown 早报，返回文本。"""
    return call_llm(REPORT_SYSTEM_PROMPT, user_prompt)


def generate_voice_script(user_prompt):
    """调用 LLM 生成语音播报稿，返回文本。"""
    return call_llm(VOICE_SYSTEM_PROMPT, user_prompt)


def main():
    load_dotenv()

    latest_date, articles = fetch_latest_articles()

    if not latest_date:
        print("数据库中没有文章。")
        return

    if not articles:
        print(f"日期 {latest_date} 没有找到论文。")
        return

    print(f"找到 {len(articles)} 篇论文（{latest_date}）")

    user_prompt = build_user_prompt(latest_date, articles)
    REPORTS_DIR.mkdir(exist_ok=True)

    print("正在生成 Markdown 早报...")
    report = generate_report(user_prompt)
    report_path = REPORTS_DIR / f"{latest_date}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"早报已生成: {report_path}")

    print("正在生成语音稿...")
    voice_script = generate_voice_script(user_prompt)
    voice_path = REPORTS_DIR / f"{latest_date}-voice.txt"
    voice_path.write_text(voice_script, encoding="utf-8")
    print(f"语音稿已生成: {voice_path}")


if __name__ == "__main__":
    main()
