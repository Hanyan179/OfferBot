"""
JobRAG 封装类真实测试 — 用已有的 LightRAG 数据和真实 API 验证

用法：cd boss-agent && .venv/bin/python3 scripts/test_job_rag.py
"""

import asyncio
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "boss_agent.db")
WORKING_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "lightrag_jobs")


def db_val(key):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM user_preferences WHERE key = ?", (key,)).fetchone()
    return row[0] if row else ""


async def main():
    from db.database import Database
    from rag.job_rag import JobRAG

    api_key = db_val("llm_api_key")
    base_url = db_val("llm_base_url")
    model = db_val("llm_model")

    print(f"模型: {model}")
    print(f"数据目录: {WORKING_DIR}")
    print(f"数据库: {DB_PATH}")

    # 创建 Database 实例（query_entities 需要）
    db = Database(DB_PATH)
    await db.connect()

    # --- 测试 1: is_ready 未初始化时为 False ---
    print("\n=== 测试 1: is_ready 未初始化 ===")
    rag = JobRAG(
        working_dir=WORKING_DIR,
        api_key=api_key,
        base_url=base_url,
        model=model,
        db=db,
    )
    assert not rag.is_ready, "未初始化时 is_ready 应为 False"
    print("  ✅ is_ready = False")

    # --- 测试 2: initialize 成功 ---
    print("\n=== 测试 2: initialize ===")
    await rag.initialize()
    assert rag.is_ready, "初始化后 is_ready 应为 True"
    print("  ✅ is_ready = True")

    # --- 测试 3: query_for_agent（用已有图谱数据） ---
    print("\n=== 测试 3: query_for_agent ===")
    query = "AI Agent 架构方向的岗位"
    print(f"  查询: {query}")
    result = await rag.query_for_agent(query)
    assert isinstance(result, str), "返回应为字符串"
    assert len(result) > 0, "返回不应为空"
    print(f"  ✅ 返回 {len(result)} 字符")
    print(f"  前 200 字: {result[:200]}...")

    # --- 测试 4: query_entities ---
    print("\n=== 测试 4: query_entities ===")
    query2 = "Python 后端开发"
    print(f"  查询: {query2}")
    entities = await rag.query_entities(query2)
    assert isinstance(entities, list), "返回应为列表"
    print(f"  ✅ 返回 {len(entities)} 条岗位")
    for e in entities[:3]:
        print(f"    - [{e.get('id')}] {e.get('title')} @ {e.get('company')}")

    # --- 测试 5: insert_job（插入一条测试数据） ---
    print("\n=== 测试 5: insert_job ===")
    test_job = {
        "id": 99999,
        "title": "测试岗位-JobRAG验证",
        "company": "测试公司",
        "city": "测试城市",
        "salary_min": 10,
        "salary_max": 20,
        "url": "https://example.com/test",
        "raw_jd": "这是一个用于验证 JobRAG insert_job 功能的测试岗位。",
    }
    ok = await rag.insert_job(test_job)
    print(f"  ✅ insert_job 返回: {ok}")

    # --- 测试 6: finalize ---
    print("\n=== 测试 6: finalize ===")
    await rag.finalize()
    assert not rag.is_ready, "finalize 后 is_ready 应为 False"
    print("  ✅ finalize 成功, is_ready = False")

    await db.close()
    print("\n=== 全部通过 ===")


if __name__ == "__main__":
    asyncio.run(main())
