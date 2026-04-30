"""智能筛选候选论文，调用 DeepSeek 生成中文早报，输出为 Markdown 文件。"""

import json
import os
from pathlib import Path

from openai import OpenAI

from db import (
    get_today_articles,
    get_unpushed_subscribed_articles,
    get_unpushed_all_articles,
    batch_update_embeddings,
)
from embedding import compute_embedding, semantic_search

REPORTS_DIR = Path(__file__).parent / "reports"

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename):
    """从 prompts/ 目录读取提示词文件，返回去除首尾空白的字符串。"""
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


REPORT_SYSTEM_PROMPT = _load_prompt("report_system.txt")
VOICE_SYSTEM_PROMPT = _load_prompt("voice_system.txt")
SELECT_SYSTEM_PROMPT = _load_prompt("select_system.txt")


def _ensure_embeddings(conn, candidates):
    """检查候选文章的 embedding，缺失的批量计算并存入 DB。返回带 embedding 的 dict 列表。"""
    result = []
    updates = []
    for a in candidates:
        article = dict(a)
        if article["embedding"] is None:
            text = f"{article['title']} {article['summary'] or ''}"
            emb = compute_embedding(text)
            article["embedding"] = emb
            updates.append((emb, article["id"]))
        result.append(article)
    if updates:
        batch_update_embeddings(conn, updates)
    return result


def fetch_candidate_articles(
    conn, user_id, today, target_count=10, interests=None, pool_size=50
):
    """
    智能筛选候选文章：
    1. 三级策略取 pool_size 篇候选池
    2. Lazy 补算缺失的 embedding
    3. 有 interests → 语义排序取 top target_count
       无 interests → 直接取前 target_count 篇
    返回 (候选文章列表, 当天文章列表)
    """
    today_articles = get_today_articles(conn, user_id, today)
    candidates = list(today_articles)
    candidate_ids = [a["id"] for a in candidates]

    if len(candidates) < pool_size:
        remaining = pool_size - len(candidates)
        subscribed = get_unpushed_subscribed_articles(
            conn, user_id, candidate_ids, remaining
        )
        candidates.extend(subscribed)
        candidate_ids = [a["id"] for a in candidates]

    if len(candidates) < pool_size:
        remaining = pool_size - len(candidates)
        all_articles = get_unpushed_all_articles(
            conn, user_id, candidate_ids, remaining
        )
        candidates.extend(all_articles)

    if interests and len(candidates) > target_count:
        candidates = _ensure_embeddings(conn, candidates)
        candidates = semantic_search(interests, candidates, top_k=target_count)

    else:
        candidates = candidates[:target_count]

    return candidates, today_articles


def build_selection_prompt(candidates, interests=None):
    """将候选文章列表组装为发给 LLM 的选择 prompt。"""
    if interests:
        lines = [
            f"以下是 {len(candidates)} 篇候选论文，请从中选择 2-3 篇最值得推荐的论文。\n",
            f"用户的研究兴趣为：{interests}\n",
        ]
    else:
        lines = [
            f"以下是 {len(candidates)} 篇候选论文，请从中选择 2-3 篇最值得推荐的论文：\n"
        ]

    for i, a in enumerate(candidates):
        authors = ", ".join(json.loads(a["authors"]))
        lines.append(f"--- 论文 {i} ---")
        lines.append(f"期刊: {a['feed_name']}")
        lines.append(f"标题: {a['title']}")
        lines.append(f"作者: {authors}")
        lines.append(f"链接: {a['link']}")
        lines.append(f"摘要: {a['summary'] or '无'}")
        lines.append("")

    return "\n".join(lines)


def select_articles(candidates, interests=None):
    """调用 LLM 从候选文章中选择 2-3 篇，返回选中的文章列表。"""
    if len(candidates) <= 3:
        return candidates

    selection_prompt = build_selection_prompt(candidates, interests)
    response = call_llm(SELECT_SYSTEM_PROMPT, selection_prompt)

    try:
        # 解析 JSON 响应
        result = json.loads(response.strip())
        selected_indices = result.get("selected", [])
        # 验证索引有效性
        selected_indices = [i for i in selected_indices if 0 <= i < len(candidates)]
        if not selected_indices:
            # 如果没有有效索引，返回前 3 篇
            return candidates[:3]
        return [candidates[i] for i in selected_indices]
    except json.JSONDecodeError, KeyError:
        # 解析失败，返回前 3 篇
        print("ERROR: ai 挑选失败，返回候选的前三篇")
        return candidates[:3]


def build_user_prompt(date, articles):
    """将论文列表组装为发给 LLM 的用户 prompt。"""
    lines = [f"当前日期是 {date}，以下是 {len(articles)} 篇论文：\n"]

    for i, a in enumerate(articles, 1):
        authors = ", ".join(json.loads(a["authors"]))
        lines.append(f"--- 论文 {i} ---")
        lines.append(f"期刊: {a['feed_name']}")
        lines.append(f"标题: {a['title']}")
        lines.append(f"作者: {authors}")
        lines.append(f"链接: {a['link']}")
        lines.append(f"摘要: {a['summary'] or '无'}")
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


def generate_voice_script(report, user_prompt):
    """调用 LLM 生成语音播报稿，返回文本。

    参数：
    - report: 已生成的 Markdown 早报文本
    - user_prompt: 原始论文数据 prompt
    """
    combined_prompt = (
        "以下是已生成的早报：\n\n"
        f"{report}\n\n"
        "---\n\n"
        "以下是原始论文数据：\n\n"
        f"{user_prompt}"
    )
    return call_llm(VOICE_SYSTEM_PROMPT, combined_prompt)
