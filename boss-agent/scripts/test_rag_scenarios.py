"""
LightRAG 集成测试 — 6 个业务场景的真实 LLM 验证

用法：cd boss-agent && python3 scripts/test_rag_scenarios.py

测试场景：
  S1: 画像匹配推荐 — "我的画像适合什么工作"
  S2: 条件筛选 — "帮我找上海 40K+ 的 AI 岗位"
  S3: 相似推荐 — "找跟 AI Agent 引擎架构类似的岗位"
  S4: 匹配度分析 — "这个岗位跟我匹配吗"
  S5: 知识问答 — "Agent 岗位的技能需求 TOP10"
  S6: 精确查找 — "京东有什么岗位"
"""

import asyncio
import json
import sys
import os
import httpx

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:7860")


async def test_scenario(name: str, message: str, expect_tools: list[str] | None = None):
    """发送真实 LLM 请求，验证 agent 行为。"""
    print(f"\n{'='*60}")
    print(f"场景: {name}")
    print(f"输入: {message}")
    print(f"{'='*60}")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{BASE_URL}/api/test/chat",
            json={"message": message},
        )

    if resp.status_code != 200:
        print(f"❌ HTTP {resp.status_code}: {resp.text[:200]}")
        return False

    data = resp.json()
    if not data.get("ok"):
        print(f"❌ 请求失败: {data.get('error', 'unknown')}")
        return False

    # 分析结果
    reply = data.get("reply", "")
    tool_calls = data.get("tool_calls", [])
    tools_used = [tc["name"] for tc in tool_calls]
    duration = data.get("total_duration_ms", 0)

    print(f"耗时: {duration}ms")
    print(f"调用工具: {tools_used}")
    print(f"回复预览: {reply[:200]}")

    # 验证
    ok = True
    if expect_tools:
        for et in expect_tools:
            if et not in tools_used:
                print(f"⚠️  预期调用 {et}，但未调用")
                ok = False

    print(f"{'✅ 通过' if ok else '⚠️ 需检查'}")
    return ok


async def main():
    print("LightRAG 集成测试 — 6 个业务场景")
    print(f"目标: {BASE_URL}")

    # 先检查服务是否可用
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{BASE_URL}/api/health")
            if r.status_code != 200:
                print(f"❌ 服务不可用: {r.status_code}")
                sys.exit(1)
    except Exception as e:
        print(f"❌ 无法连接服务: {e}")
        sys.exit(1)

    results = {}

    # S1: 画像匹配推荐（agent 需要消费向量检索结果来回答）
    results["S1"] = await test_scenario(
        "S1: 画像匹配推荐",
        "根据我的画像，目前有哪些岗位适合我？",
        expect_tools=["get_user_profile"],
    )

    # S2: 条件筛选（SQL 查询，结果推前端）
    results["S2"] = await test_scenario(
        "S2: 条件筛选",
        "帮我找上海 40K 以上的 AI 岗位",
        expect_tools=["query_jobs"],
    )

    # S3: 相似推荐（向量检索相似岗位）
    results["S3"] = await test_scenario(
        "S3: 相似推荐",
        "找跟 AI Agent 引擎架构类似的岗位",
    )

    # S4: 匹配度分析（图谱检索技能对比）
    results["S4"] = await test_scenario(
        "S4: 匹配度分析",
        "3756 这个岗位跟我的技能匹配吗？帮我分析一下差距",
    )

    # S5: 知识问答（图谱聚合）
    results["S5"] = await test_scenario(
        "S5: 知识问答",
        "目前市场上 AI Agent 岗位最常要求的技能 TOP10 是什么？",
    )

    # S6: 精确查找（SQL 精确匹配）
    results["S6"] = await test_scenario(
        "S6: 精确查找",
        "京东有什么岗位？",
        expect_tools=["query_jobs"],
    )

    # 汇总
    print(f"\n{'='*60}")
    print("测试汇总")
    print(f"{'='*60}")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, ok in results.items():
        print(f"  {name}: {'✅' if ok else '⚠️'}")
    print(f"\n通过: {passed}/{total}")


if __name__ == "__main__":
    asyncio.run(main())
