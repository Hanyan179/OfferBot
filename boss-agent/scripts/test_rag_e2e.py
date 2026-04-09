"""
LightRAG 端到端测试 — 验证检索精准度

自动检测 embedding 兼容性，不兼容时重建图谱。
记录结果到控制台 + JSON 文件。

用法：
  python3 scripts/test_rag_e2e.py           # 自动检测，必要时重建
  python3 scripts/test_rag_e2e.py --rebuild  # 强制重建
  python3 scripts/test_rag_e2e.py --query "xxx"  # 单条查询
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

DB_PATH = str(_root / "db" / "boss_agent.db")
WORKING_DIR = str(_root / "data" / "lightrag_jobs")
REPORT_PATH = str(_root / "data" / "rag_e2e_report.json")

# DashScope text-embedding-v3 支持的维度
EMBED_DIM = 1024
EMBED_MODEL = "text-embedding-v3"
EMBED_MAX_INPUT = 8000


def db_val(key: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT value FROM user_preferences WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    return row[0] if row else ""


def get_existing_dim() -> int | None:
    """从已有 vdb 文件检测 embedding 维度"""
    for name in ("vdb_entities.json", "vdb_chunks.json"):
        path = os.path.join(WORKING_DIR, name)
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict) and "embedding_dim" in data:
                return data["embedding_dim"]
    return None


def get_jobs_with_jd() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, company, city, salary_min, salary_max, url, raw_jd, "
        "skills_must, skills_preferred, responsibilities, experience_min, "
        "experience_max, education, company_industry "
        "FROM jobs WHERE raw_jd IS NOT NULL AND raw_jd != ''"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def build_document(job: dict) -> str:
    """构建岗位文档（和 JobRAG._build_document 一致）"""
    sal_min = job.get("salary_min", "")
    sal_max = job.get("salary_max", "")
    salary = f"{sal_min}-{sal_max}K" if sal_min and sal_max else ""
    return (
        f"【岗位ID】{job.get('id', '')}\n"
        f"【岗位】{job.get('title', '')}\n"
        f"【公司】{job.get('company', '')}\n"
        f"【城市】{job.get('city', '')}\n"
        f"【薪资】{salary}\n"
        f"【链接】{job.get('url', '')}\n"
        f"【职位描述】{job.get('raw_jd', '')}"
    )


TEST_QUERIES = [
    ("需要 Python 和 RAG 的岗位", "技能匹配"),
    ("上海的 AI 岗位", "城市筛选"),
    ("京东的岗位有哪些", "公司查找"),
    ("40K 以上的岗位", "薪资范围"),
    ("适合 5 年 Java 后端转 AI 的岗位", "画像匹配"),
    ("AI Agent 架构师相关的岗位", "相似推荐"),
    ("需要 LangChain 和大模型经验的岗位", "技能组合"),
    ("哪些公司在招 Agent 方向", "知识问答"),
    ("AI 岗位技能需求 TOP10", "趋势分析"),
    ("需要分布式系统经验的岗位", "技能匹配2"),
    ("类似 AI Agent 研发工程师的岗位", "相似推荐2"),
    ("北京的大模型岗位", "城市+技能"),
]


async def create_rag(api_key: str, base_url: str, model: str):
    """创建 LightRAG 实例"""
    from lightrag import LightRAG
    from lightrag.llm.openai import openai_complete_if_cache
    from lightrag.utils import EmbeddingFunc
    from openai import AsyncOpenAI

    async def llm_func(prompt, system_prompt=None, history_messages=[], **kw):
        return await openai_complete_if_cache(
            model, prompt, system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=api_key, base_url=base_url, **kw,
        )

    _client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def embed_func(texts: list[str]) -> np.ndarray:
        resp = await _client.embeddings.create(
            model=EMBED_MODEL,
            input=[t[:EMBED_MAX_INPUT] for t in texts],
            dimensions=EMBED_DIM,
        )
        return np.array([e.embedding for e in resp.data], dtype=np.float32)

    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=llm_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBED_DIM, max_token_size=8192, func=embed_func,
        ),
        addon_params={
            "entity_types": ["岗位", "公司", "技能", "城市", "薪资", "职责", "任职要求", "行业"],
            "language": "Chinese",
        },
    )
    return rag


async def rebuild_graph(rag) -> int:
    """重建图谱：清空数据 → 重新插入所有岗位"""
    print("\n🔄 重建图谱...")

    # 清空
    if os.path.exists(WORKING_DIR):
        shutil.rmtree(WORKING_DIR)
    os.makedirs(WORKING_DIR, exist_ok=True)
    print("   ✅ 数据目录已清空")

    # 重新初始化存储
    await rag.initialize_storages()

    # 插入
    jobs = get_jobs_with_jd()
    print(f"   📦 待插入: {len(jobs)} 条岗位")

    t0 = time.time()
    for i, job in enumerate(jobs, 1):
        doc = build_document(job)
        try:
            await rag.ainsert(doc)
            if i % 5 == 0 or i == len(jobs):
                elapsed = time.time() - t0
                print(f"   [{i}/{len(jobs)}] {job['title'][:20]} ({elapsed:.0f}s)")
        except Exception as e:
            print(f"   ❌ 插入失败 (id={job.get('id')}): {e}")

    elapsed = time.time() - t0
    print(f"   ✅ 重建完成: {len(jobs)} 条, {elapsed:.0f}s\n")
    return len(jobs)


async def run_tests(rag, queries: list[tuple[str, str]]) -> list[dict]:
    """执行测试查询"""
    from lightrag import QueryParam

    db_conn = sqlite3.connect(DB_PATH)
    db_conn.row_factory = sqlite3.Row
    results = []

    for i, (query, scenario) in enumerate(queries, 1):
        print(f"\n[{i}/{len(queries)}] 🔍 {scenario}: {query}")
        print("-" * 50)
        result = {"index": i, "query": query, "scenario": scenario}

        # aquery (answer)
        t0 = time.time()
        try:
            answer = str(await rag.aquery(query, param=QueryParam(mode="hybrid")))
        except Exception as e:
            answer = f"[ERROR] {e}"
        answer_ms = int((time.time() - t0) * 1000)
        result["answer_time_ms"] = answer_ms
        result["answer_length"] = len(answer)
        result["answer_text"] = answer

        preview = answer[:300].replace("\n", " ")
        if len(answer) > 300:
            preview += "..."
        print(f"  📝 answer ({answer_ms}ms, {len(answer)}字): {preview}")

        # aquery_data (search)
        t0 = time.time()
        try:
            data = await rag.aquery_data(query, param=QueryParam(mode="hybrid"))
        except Exception as e:
            data = {"status": "error"}
        search_ms = int((time.time() - t0) * 1000)

        job_ids: list[int] = []
        if data.get("status") == "success":
            inner = data.get("data", {})
            for src in ("chunks", "entities", "relationships"):
                for item in inner.get(src, []):
                    for field in ("content", "description", "source_id"):
                        for m in re.finditer(r"【岗位ID】(\d+)", item.get(field, "")):
                            jid = int(m.group(1))
                            if jid not in job_ids:
                                job_ids.append(jid)

        jobs_detail = []
        if job_ids:
            ph = ",".join("?" * len(job_ids))
            rows = db_conn.execute(
                f"SELECT id, title, company, salary_min, salary_max, url "
                f"FROM jobs WHERE id IN ({ph})", tuple(job_ids),
            ).fetchall()
            row_map = {r["id"]: dict(r) for r in rows}
            jobs_detail = [row_map[jid] for jid in job_ids if jid in row_map]

        result["search_time_ms"] = search_ms
        result["search_count"] = len(jobs_detail)
        result["search_job_ids"] = [j["id"] for j in jobs_detail]
        result["search_jobs"] = [f"{j['title']} @ {j['company']}" for j in jobs_detail[:5]]

        print(f"  📋 search ({search_ms}ms): {len(jobs_detail)} 条岗位")
        for j in jobs_detail[:5]:
            sal = f"{j.get('salary_min','?')}-{j.get('salary_max','?')}K" if j.get("salary_min") else "?"
            print(f"     - {j['title']} @ {j['company']} ({sal})")
        if len(jobs_detail) > 5:
            print(f"     ... 还有 {len(jobs_detail) - 5} 条")

        results.append(result)

    db_conn.close()
    return results


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="强制重建图谱")
    parser.add_argument("--query", type=str, help="单条查询")
    args = parser.parse_args()

    api_key = db_val("llm_api_key")
    base_url = db_val("llm_base_url")
    model = db_val("llm_model")

    if not api_key:
        print("❌ 未找到 LLM API Key")
        return

    print(f"🔧 LLM: {model}")
    print(f"📐 Embedding: {EMBED_MODEL} ({EMBED_DIM}维)")
    print(f"📂 图谱: {WORKING_DIR}")

    rag = None  # 延迟创建

    # 检查是否需要重建
    existing_dim = get_existing_dim()
    need_rebuild = args.rebuild
    if existing_dim and existing_dim != EMBED_DIM:
        print(f"\n⚠️  已有数据维度 {existing_dim} ≠ 当前配置 {EMBED_DIM}，需要重建")
        need_rebuild = True
    elif not existing_dim:
        print("\n⚠️  无已有图谱数据，需要构建")
        need_rebuild = True

    if need_rebuild:
        # 先清空目录，再创建 rag 实例
        if os.path.exists(WORKING_DIR):
            shutil.rmtree(WORKING_DIR)
        os.makedirs(WORKING_DIR, exist_ok=True)
        print("   ✅ 数据目录已清空")

        rag = await create_rag(api_key, base_url, model)
        await rag.initialize_storages()

        # 插入岗位
        jobs = get_jobs_with_jd()
        print(f"   📦 待插入: {len(jobs)} 条岗位")
        t0 = time.time()
        for i, job in enumerate(jobs, 1):
            doc = build_document(job)
            try:
                await rag.ainsert(doc)
                if i % 5 == 0 or i == len(jobs):
                    elapsed = time.time() - t0
                    print(f"   [{i}/{len(jobs)}] {job['title'][:20]} ({elapsed:.0f}s)")
            except Exception as e:
                print(f"   ❌ 插入失败 (id={job.get('id')}): {e}")
        elapsed = time.time() - t0
        print(f"   ✅ 重建完成: {len(jobs)} 条, {elapsed:.0f}s\n")
    else:
        rag = await create_rag(api_key, base_url, model)
        await rag.initialize_storages()
        print("✅ 使用已有图谱数据\n")

    # 图谱统计
    graphml_path = os.path.join(WORKING_DIR, "graph_chunk_entity_relation.graphml")
    if os.path.exists(graphml_path):
        import networkx as nx
        from collections import Counter
        G = nx.read_graphml(graphml_path)
        types = Counter(d.get("entity_type", "?") for _, d in G.nodes(data=True))
        print(f"📈 图谱: {G.number_of_nodes()} 实体, {G.number_of_edges()} 关系")
        for t, c in types.most_common():
            print(f"   {t}: {c}")
        print()

    # 确定查询列表
    if args.query:
        queries = [(args.query, "自定义")]
    else:
        queries = TEST_QUERIES

    print(f"📊 测试: {len(queries)} 条")
    print("=" * 70)

    results = await run_tests(rag, queries)

    # 汇总
    print("\n" + "=" * 70)
    print("\n📊 汇总报告\n")
    print(f"{'#':<3} {'场景':<12} {'answer_ms':>10} {'answer_len':>10} {'search_ms':>10} {'search_cnt':>10}")
    print("-" * 65)
    for r in results:
        print(f"{r['index']:<3} {r['scenario']:<12} {r['answer_time_ms']:>10} {r['answer_length']:>10} {r['search_time_ms']:>10} {r['search_count']:>10}")

    if results:
        avg_a = sum(r["answer_time_ms"] for r in results) / len(results)
        avg_s = sum(r["search_time_ms"] for r in results) / len(results)
        total = sum(r["search_count"] for r in results)
        print("-" * 65)
        print(f"{'AVG':<15} {avg_a:>10.0f} {'':>10} {avg_s:>10.0f} {total:>10}")

    # 保存报告
    report = {
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "embedding": f"{EMBED_MODEL} ({EMBED_DIM}d)",
        "results": results,
        "summary": {
            "total_queries": len(results),
            "avg_answer_ms": round(avg_a) if results else 0,
            "avg_search_ms": round(avg_s) if results else 0,
            "total_search_results": total if results else 0,
        },
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n💾 报告: {REPORT_PATH}")

    await rag.finalize_storages()
    print("✅ 完成")


if __name__ == "__main__":
    asyncio.run(main())
