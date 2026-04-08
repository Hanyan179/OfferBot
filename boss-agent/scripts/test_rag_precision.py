#!/usr/bin/env python3
"""
LightRAG 检索精准度测试脚本

用法：
  cd boss-agent && python scripts/test_rag_precision.py          # 运行所有预定义查询
  python scripts/test_rag_precision.py --query "Python AI 岗位"  # 单条查询
  python scripts/test_rag_precision.py --rebuild                 # 重建图谱后测试
  python scripts/test_rag_precision.py --graph-stats             # 图谱统计报告
  python scripts/test_rag_precision.py --check-entity "Python"   # 实体详情
  python scripts/test_rag_precision.py --vector-stats            # 向量存储统计
  python scripts/test_rag_precision.py --vector-search "Python AI Agent"  # 向量检索
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import load_config
from db.database import Database
from rag.job_rag import JobRAG

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 预定义测试查询（10+ 条，覆盖多种场景）
# ---------------------------------------------------------------------------
TEST_QUERIES = [
    # 技能匹配
    {"query": "需要 Python 和 RAG 的岗位", "category": "技能匹配"},
    {"query": "要求 LangChain 和 LLM 开发经验的职位", "category": "技能匹配"},
    {"query": "需要 Java 和分布式系统经验的岗位", "category": "技能匹配"},
    # 城市筛选
    {"query": "上海的 AI 岗位", "category": "城市筛选"},
    {"query": "北京的后端开发岗位", "category": "城市筛选"},
    # 公司查找
    {"query": "京东的岗位有哪些", "category": "公司查找"},
    {"query": "字节跳动的技术岗位", "category": "公司查找"},
    # 薪资范围
    {"query": "40K 以上的岗位", "category": "薪资范围"},
    {"query": "薪资 60-100K 的 AI 岗位", "category": "薪资范围"},
    # 画像匹配
    {"query": "适合 5 年 Java 后端转 AI 的岗位", "category": "画像匹配"},
    {"query": "适合应届硕士做 NLP 方向的岗位", "category": "画像匹配"},
    # 相似推荐
    {"query": "类似 AI Agent 架构师的岗位", "category": "相似推荐"},
    {"query": "和大模型应用开发相关的岗位", "category": "相似推荐"},
]


# ---------------------------------------------------------------------------
# 辅助：初始化 JobRAG 实例
# ---------------------------------------------------------------------------

async def _create_job_rag(cfg) -> tuple[JobRAG, Database]:
    """创建并初始化 JobRAG 和 Database。"""
    db = Database(cfg.db_path)
    await db.connect()

    rag = JobRAG(
        working_dir=str(PROJECT_ROOT / "data" / "lightrag_jobs"),
        api_key=cfg.dashscope_api_key,
        base_url=cfg.api_base_url,
        model=cfg.dashscope_llm_model,
        db=db,
    )
    await rag.initialize()
    return rag, db


# ---------------------------------------------------------------------------
# 11.1 检索精准度测试
# ---------------------------------------------------------------------------

def _count_job_mentions(text: str) -> int:
    """统计回答文本中提及的岗位数量（通过【岗位ID】标记）。"""
    return len(set(re.findall(r"【岗位ID】(\d+)", text)))


async def run_precision_test(
    rag: JobRAG, queries: list[dict], *, verbose: bool = True
) -> list[dict]:
    """对每条查询分别调用 query_for_agent 和 query_entities，收集结果。"""
    results: list[dict] = []

    for item in queries:
        q = item["query"]
        cat = item["category"]

        # query_for_agent
        t0 = time.time()
        answer = await rag.query_for_agent(q)
        agent_ms = int((time.time() - t0) * 1000)

        # query_entities
        t0 = time.time()
        entities = await rag.query_entities(q)
        entity_ms = int((time.time() - t0) * 1000)

        job_ids = [e.get("id") for e in entities]
        row = {
            "category": cat,
            "query": q,
            "answer_len": len(answer),
            "answer_jobs": _count_job_mentions(answer),
            "answer_ms": agent_ms,
            "entity_count": len(entities),
            "entity_ids": job_ids,
            "entity_ms": entity_ms,
        }
        results.append(row)

    if verbose:
        _print_precision_report(results)
    return results


def _print_precision_report(results: list[dict]) -> None:
    """输出结构化控制台表格报告。"""
    sep = "-" * 120
    header = (
        f"{'类别':<10} {'查询':<30} {'回答长度':>8} {'回答岗位':>8} "
        f"{'回答耗时':>8} {'实体数':>6} {'实体耗时':>8} {'岗位ID列表'}"
    )
    print(f"\n{'=' * 120}")
    print("检索精准度测试报告")
    print(f"{'=' * 120}")
    print(header)
    print(sep)

    for r in results:
        ids_str = ",".join(str(i) for i in r["entity_ids"][:5])
        if len(r["entity_ids"]) > 5:
            ids_str += f"...+{len(r['entity_ids']) - 5}"
        print(
            f"{r['category']:<10} {r['query']:<30} {r['answer_len']:>8} "
            f"{r['answer_jobs']:>8} {r['answer_ms']:>7}ms "
            f"{r['entity_count']:>6} {r['entity_ms']:>7}ms {ids_str}"
        )

    print(sep)
    total_agent = sum(r["answer_ms"] for r in results)
    total_entity = sum(r["entity_ms"] for r in results)
    avg_entities = sum(r["entity_count"] for r in results) / max(len(results), 1)
    print(
        f"汇总: {len(results)} 条查询 | "
        f"回答总耗时 {total_agent}ms | "
        f"实体总耗时 {total_entity}ms | "
        f"平均返回岗位 {avg_entities:.1f} 条"
    )
    print()


# ---------------------------------------------------------------------------
# 11.2 图谱质量验证
# ---------------------------------------------------------------------------

async def run_graph_stats(rag: JobRAG, db: Database) -> None:
    """输出图谱统计报告，含自动质量检查。"""
    stats = rag.get_graph_stats()
    if "error" in stats:
        print(f"[错误] {stats['error']}")
        return

    print(f"\n{'=' * 80}")
    print("图谱统计报告")
    print(f"{'=' * 80}")
    print(f"实体总数: {stats['total_entities']}")
    print(f"关系总数: {stats['total_relations']}")
    print(f"孤立实体: {stats['isolated_entities']}")

    # 按类型分组
    print(f"\n--- 实体类型分布 ---")
    for etype, count in sorted(
        stats["entity_types"].items(), key=lambda x: -x[1]
    ):
        print(f"  {etype}: {count}")

    # TOP 20 高频技能
    skills = rag.get_entities_by_type("技能")
    if skills:
        print(f"\n--- TOP 20 高频技能（共 {len(skills)} 个） ---")
        # 按关系数排序
        import networkx as nx

        gpath = os.path.join(
            rag._working_dir, "graph_chunk_entity_relation.graphml"
        )
        G = nx.read_graphml(gpath)
        skill_degrees = [(s, G.degree(s)) for s in skills if s in G]
        skill_degrees.sort(key=lambda x: -x[1])
        for name, deg in skill_degrees[:20]:
            print(f"  {name}: {deg} 条关系")

    # TOP 10 高频公司
    companies = rag.get_entities_by_type("公司")
    if companies:
        print(f"\n--- TOP 10 高频公司（共 {len(companies)} 个） ---")
        comp_degrees = [(c, G.degree(c)) for c in companies if c in G]
        comp_degrees.sort(key=lambda x: -x[1])
        for name, deg in comp_degrees[:10]:
            print(f"  {name}: {deg} 条关系")

    # 关系类型分布
    if os.path.exists(gpath):
        rel_types = Counter()
        for u, v, d in G.edges(data=True):
            rel_types[d.get("relationship_type", d.get("label", "unknown"))] += 1
        print(f"\n--- 关系类型分布 ---")
        for rtype, count in rel_types.most_common(15):
            print(f"  {rtype}: {count}")

    # 孤立实体列表
    if stats["isolated_entities"] > 0:
        isolated_names = [n for n in G.nodes() if G.degree(n) == 0]
        print(f"\n--- 孤立实体（前 20 个） ---")
        for name in isolated_names[:20]:
            print(f"  {name}")
        if len(isolated_names) > 20:
            print(f"  ...还有 {len(isolated_names) - 20} 个")

    # --- 自动质量检查 ---
    print(f"\n{'=' * 80}")
    print("图谱质量自动检查")
    print(f"{'=' * 80}")

    # 1. 技能去重率检查
    if skills:
        # 简单检查：同一技能是否有多个变体（如 React 和 React.js）
        lower_map: dict[str, list[str]] = {}
        for s in skills:
            key = re.sub(r"[.\-_/]", "", s.lower().strip())
            lower_map.setdefault(key, []).append(s)
        duplicates = {k: v for k, v in lower_map.items() if len(v) > 1}
        if duplicates:
            print(f"[警告] 发现 {len(duplicates)} 组可能重复的技能实体:")
            for variants in list(duplicates.values())[:10]:
                print(f"  {' / '.join(variants)}")
        else:
            print("[通过] 技能实体无明显重复")

    # 2. 岗位覆盖率
    rows = await db.execute(
        "SELECT COUNT(*) as cnt FROM jobs WHERE raw_jd IS NOT NULL AND raw_jd != ''"
    )
    db_job_count = rows[0]["cnt"] if rows else 0
    graph_jobs = rag.get_entities_by_type("岗位")
    graph_job_count = len(graph_jobs)
    if db_job_count > 0:
        coverage = graph_job_count / db_job_count * 100
        status = "[通过]" if coverage >= 80 else "[警告]"
        print(
            f"{status} 岗位覆盖率: {graph_job_count}/{db_job_count} "
            f"({coverage:.1f}%)"
        )
    else:
        print("[信息] 数据库中无有效岗位数据")

    # 3. 孤立实体比例
    total = stats["total_entities"]
    isolated = stats["isolated_entities"]
    if total > 0:
        ratio = isolated / total * 100
        status = "[通过]" if ratio < 10 else "[警告]"
        print(f"{status} 孤立实体比例: {isolated}/{total} ({ratio:.1f}%)")

    # 4. 关系完整性：每个岗位实体至少有一个关系
    if graph_jobs:
        no_rel = sum(1 for j in graph_jobs if j in G and G.degree(j) == 0)
        status = "[通过]" if no_rel == 0 else "[警告]"
        print(
            f"{status} 无关系的岗位实体: {no_rel}/{graph_job_count}"
        )

    print()


async def run_check_entity(rag: JobRAG, entity_name: str) -> None:
    """输出指定实体的详情和关联关系。"""
    print(f"\n{'=' * 80}")
    print(f"实体详情: {entity_name}")
    print(f"{'=' * 80}")

    relations = rag.get_relations_for_entity(entity_name)
    if not relations:
        print(f"未找到实体 '{entity_name}' 或该实体无关系")
        return

    print(f"关系数量: {len(relations)}")
    print(f"\n--- 关系列表 ---")
    for rel in relations:
        src = rel.get("source", "")
        tgt = rel.get("target", "")
        rtype = rel.get("relationship_type", rel.get("label", ""))
        desc = rel.get("description", "")[:80]
        direction = "→" if src == entity_name else "←"
        other = tgt if src == entity_name else src
        print(f"  {direction} [{rtype}] {other}")
        if desc:
            print(f"    {desc}")
    print()


# ---------------------------------------------------------------------------
# 11.3 向量化质量验证
# ---------------------------------------------------------------------------

def _load_kv_store_count(working_dir: str, name: str) -> int:
    """读取 kv_store JSON 文件的条目数。"""
    fpath = os.path.join(working_dir, f"{name}.json")
    if not os.path.exists(fpath):
        return 0
    try:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        return len(data)
    except (json.JSONDecodeError, OSError):
        return 0


def _check_vector_dimension(working_dir: str, name: str) -> int | None:
    """检查向量文件中第一个向量的维度。"""
    fpath = os.path.join(working_dir, f"{name}.json")
    if not os.path.exists(fpath):
        return None
    try:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, dict) and "embedding" in val:
                    emb = val["embedding"]
                    if isinstance(emb, list):
                        return len(emb)
                # nano-vectordb 格式: list of lists
                if isinstance(val, list) and len(val) > 0:
                    return len(val)
                break
        elif isinstance(data, list) and len(data) > 0:
            item = data[0]
            if isinstance(item, dict) and "embedding" in item:
                return len(item["embedding"])
    except (json.JSONDecodeError, OSError):
        pass
    return None


async def run_vector_stats(rag: JobRAG) -> None:
    """输出向量存储统计报告，含自动质量检查。"""
    stats = rag.get_vector_stats()
    working_dir = rag._working_dir

    print(f"\n{'=' * 80}")
    print("向量存储统计报告")
    print(f"{'=' * 80}")

    for name, info in stats.items():
        missing = info.get("missing", False)
        count = info.get("count", 0)
        status = "缺失" if missing else f"{count} 条"
        print(f"  {name}: {status}")

    # --- 自动质量检查 ---
    print(f"\n--- 向量化质量检查 ---")

    # 1. chunk 向量覆盖率
    kv_chunks = _load_kv_store_count(working_dir, "kv_store_text_chunks")
    vdb_chunks = stats.get("vdb_chunks", {}).get("count", 0)
    if kv_chunks > 0:
        coverage = vdb_chunks / kv_chunks * 100
        status = "[通过]" if coverage >= 95 else "[警告]"
        print(f"{status} chunk 向量覆盖率: {vdb_chunks}/{kv_chunks} ({coverage:.1f}%)")
    else:
        print("[信息] 无 kv_store_text_chunks 数据")

    # 2. 实体向量覆盖率
    kv_entities = _load_kv_store_count(working_dir, "kv_store_full_entities")
    vdb_entities = stats.get("vdb_entities", {}).get("count", 0)
    if kv_entities > 0:
        coverage = vdb_entities / kv_entities * 100
        status = "[通过]" if coverage >= 95 else "[警告]"
        print(
            f"{status} 实体向量覆盖率: {vdb_entities}/{kv_entities} ({coverage:.1f}%)"
        )
    else:
        print("[信息] 无 kv_store_full_entities 数据")

    # 3. 向量维度一致性
    expected_dim = 1024  # 配置的 embedding_dim
    for vdb_name in ("vdb_chunks", "vdb_entities", "vdb_relationships"):
        dim = _check_vector_dimension(working_dir, vdb_name)
        if dim is not None:
            status = "[通过]" if dim == expected_dim else "[警告]"
            print(f"{status} {vdb_name} 维度: {dim} (期望 {expected_dim})")

    # 4. 向量数量为 0 但有文档数据时告警
    if kv_chunks > 0 and vdb_chunks == 0:
        print("[告警] 向量化未完成: 有 chunk 数据但无向量，需要重建图谱")
    if kv_entities > 0 and vdb_entities == 0:
        print("[告警] 实体向量化未完成: 有实体数据但无向量")

    print()


async def run_vector_search(rag: JobRAG, query: str) -> None:
    """调用 naive 模式输出 top-5 结果，并对比四种模式。"""
    print(f"\n{'=' * 80}")
    print(f"向量检索测试: {query}")
    print(f"{'=' * 80}")

    # naive 模式 top-5
    print(f"\n--- naive 模式（纯向量检索）top-5 ---")
    t0 = time.time()
    result = await rag.query_for_agent(query, mode="naive", top_k=5)
    elapsed = int((time.time() - t0) * 1000)
    print(f"耗时: {elapsed}ms")
    print(f"结果长度: {len(result)} 字符")
    # 截取前 500 字符展示
    print(result[:500])
    if len(result) > 500:
        print("...(已截断)")

    # 四种模式对比
    print(f"\n--- 四种检索模式对比 ---")
    modes = ["naive", "local", "global", "hybrid"]
    print(f"{'模式':<10} {'耗时':>8} {'结果长度':>10} {'提及岗位':>8}")
    print("-" * 50)

    for mode in modes:
        t0 = time.time()
        text = await rag.query_for_agent(query, mode=mode)
        ms = int((time.time() - t0) * 1000)
        job_count = _count_job_mentions(text)
        print(f"{mode:<10} {ms:>7}ms {len(text):>10} {job_count:>8}")

    print()


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LightRAG 检索精准度测试脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--query", type=str, default=None,
        help="运行单条查询（默认运行所有预定义查询）",
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="重建图谱后再执行测试",
    )
    parser.add_argument(
        "--graph-stats", action="store_true", dest="graph_stats",
        help="输出图谱统计报告和质量检查",
    )
    parser.add_argument(
        "--check-entity", type=str, default=None, dest="check_entity",
        help="输出指定实体的详情和关联关系",
    )
    parser.add_argument(
        "--vector-stats", action="store_true", dest="vector_stats",
        help="输出向量存储统计报告和质量检查",
    )
    parser.add_argument(
        "--vector-search", type=str, default=None, dest="vector_search",
        help="向量检索测试，对比四种模式",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="启用 DEBUG 日志",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    # 日志配置
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    cfg = load_config()
    if not cfg.dashscope_api_key:
        print("[错误] 未设置 DASHSCOPE_API_KEY 环境变量")
        sys.exit(1)

    print(f"LLM: {cfg.dashscope_llm_model}")
    print(f"数据目录: {PROJECT_ROOT / 'data' / 'lightrag_jobs'}")

    rag, db = await _create_job_rag(cfg)

    try:
        if not rag.is_ready:
            print("[错误] JobRAG 初始化失败")
            sys.exit(1)

        # --rebuild
        if args.rebuild:
            print("\n开始重建图谱...")
            await rag.rebuild()
            print("图谱重建完成")

        # --graph-stats
        if args.graph_stats:
            await run_graph_stats(rag, db)

        # --check-entity
        if args.check_entity:
            await run_check_entity(rag, args.check_entity)

        # --vector-stats
        if args.vector_stats:
            await run_vector_stats(rag)

        # --vector-search
        if args.vector_search:
            await run_vector_search(rag, args.vector_search)

        # 检索精准度测试（默认行为，或 --query 单条）
        run_test = not any([
            args.graph_stats, args.check_entity,
            args.vector_stats, args.vector_search,
        ])
        if run_test or args.query:
            if args.query:
                queries = [{"query": args.query, "category": "自定义"}]
            else:
                queries = TEST_QUERIES
            await run_precision_test(rag, queries)

    finally:
        await rag.finalize()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
