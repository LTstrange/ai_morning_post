"""从数据库读取最近入库的论文，调用 DeepSeek 生成中文早报，输出为 Markdown 文件。"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from db import get_connection

REPORTS_DIR = Path(__file__).parent / "reports"

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename):
    """从 prompts/ 目录读取提示词文件，返回去除首尾空白的字符串。"""
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


REPORT_SYSTEM_PROMPT = _load_prompt("report_system.txt")
VOICE_SYSTEM_PROMPT = _load_prompt("voice_system.txt")


def fetch_latest_articles():
    """查询数据库中按发布日期降序排列的最新一批论文。"""
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
    lines = [f"当前日期是 {latest_date}，以下是最近入库的 {len(articles)} 篇论文：\n"]

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
