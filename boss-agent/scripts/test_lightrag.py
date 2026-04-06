"""
LightRAG 测试脚本 — 自定义招聘场景实体类型

用法：cd boss-agent && python3 scripts/test_lightrag.py
"""

import asyncio
import sqlite3
import os
import numpy as np

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "boss_agent.db")
WORKING_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "lightrag_jobs")

# 招聘场景实体类型
JOB_ENTITY_TYPES = [
    "岗位",       # AI Agent 研发工程师
    "公司",       # 京东、深势科技
    "技能",       # Python、LangChain、RAG
    "城市",       # 上海
    "薪资",       # 60-85K
    "职责",       # 构建 Agent 框架、分布式研发
    "任职要求",    # 3-5年经验、本科
    "行业",       # 人工智能、金融
]


def db_val(key):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM user_preferences WHERE key = ?", (key,)).fetchone()
    return row[0] if row else ""


def get_jobs_with_jd():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(
        "SELECT id, title, company, city, salary_min, salary_max, url, raw_jd "
        "FROM jobs WHERE raw_jd IS NOT NULL AND raw_jd != ''"
    ).fetchall()]


async def main():
    from lightrag import LightRAG, QueryParam
    from lightrag.llm.openai import openai_complete_if_cache
    from lightrag.utils import EmbeddingFunc
    from google import genai

    api_key = db_val("llm_api_key")
    base_url = db_val("llm_base_url")
    model = db_val("llm_model")

    print(f"LLM: {model}")
    print(f"Entity types: {JOB_ENTITY_TYPES}")
    os.makedirs(WORKING_DIR, exist_ok=True)

    async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
        return await openai_complete_if_cache(
            model, prompt,
            system_prompt=system_prompt, history_messages=history_messages,
            api_key=api_key, base_url=base_url, **kwargs,
        )

    genai_client = genai.Client(api_key=api_key)

    async def embedding_func(texts):
        resp = genai_client.models.embed_content(
            model="gemini-embedding-001", contents=[t[:8000] for t in texts],
        )
        return np.array([e.values for e in resp.embeddings], dtype=np.float32)

    # 设置自定义实体类型
    os.environ["ENTITY_TYPES"] = str(JOB_ENTITY_TYPES)

    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=llm_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=3072, max_token_size=8192, func=embedding_func,
        ),
        addon_params={"entity_types": JOB_ENTITY_TYPES, "language": "Chinese"},
    )
    await rag.initialize_storages()

    # 插入
    jobs = get_jobs_with_jd()
    print(f"\n=== 插入 {len(jobs)} 条岗位 ===")
    for job in jobs:
        doc = (
            f"【岗位】{job['title']}\n"
            f"【公司】{job['company']}\n"
            f"【城市】{job['city']}\n"
            f"【薪资】{job['salary_min']}-{job['salary_max']}K/月\n"
            f"【链接】{job['url']}\n"
            f"【岗位ID】{job['id']}\n"
            f"【职位描述】\n{job['raw_jd']}"
        )
        print(f"  插入: {job['title']}")
        await rag.ainsert(doc)

    # 查看抽取结果
    import networkx as nx
    G = nx.read_graphml(os.path.join(WORKING_DIR, 'graph_chunk_entity_relation.graphml'))
    print(f"\n=== 图谱: {G.number_of_nodes()} 节点, {G.number_of_edges()} 边 ===")

    from collections import Counter
    types = Counter(d.get('entity_type', '?') for _, d in G.nodes(data=True))
    for t, c in types.most_common():
        print(f"  {t}: {c}")

    # 查询
    print("\n=== 测试查询 ===\n")
    for q in [
        "AI Agent 架构方向的岗位",
        "需要 Python 和 Java 的岗位",
    ]:
        print(f"--- {q} ---")
        resp = await rag.aquery(q, param=QueryParam(mode="hybrid"))
        print(resp[:500] if resp else "(空)")
        print()

    await rag.finalize_storages()
    print("=== 完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
