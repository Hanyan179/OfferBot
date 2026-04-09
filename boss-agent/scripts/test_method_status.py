#!/usr/bin/env python3
"""
真实测试 method-status.md 中所有 🔧 标记的方法。
通过 POST /api/test/chat 接口，让 LLM 真实调用 Tool。
"""
import asyncio
import json
import sys
import time
import httpx

BASE = "http://localhost:7860"
TIMEOUT = 120

# 每个测试场景：message 触发 LLM 调用对应 Tool，expected_tools 是期望被调用的 tool name
SCENARIOS = [
    # === S1: 用户画像 ===
    {
        "id": "S1-1",
        "name": "search_memory",
        "message": "搜索我的记忆中关于'Python'的内容",
        "expected_tools": ["search_memory"],
        "status_tag": "🔧",
    },
    {
        "id": "S1-2",
        "name": "list_memory_categories",
        "message": "列出我所有的记忆分类",
        "expected_tools": ["list_memory_categories"],
        "status_tag": "🔧",
    },
    {
        "id": "S1-3",
        "name": "get_user_cognitive_model",
        "message": "查看我的认知模型",
        "expected_tools": ["get_user_cognitive_model"],
        "status_tag": "✅",
    },
    {
        "id": "S1-4",
        "name": "get_memory",
        "message": "查看我的求职偏好记忆",
        "expected_tools": ["get_memory"],
        "status_tag": "✅",
    },
    {
        "id": "S1-5",
        "name": "get_user_profile",
        "message": "查看我的用户档案",
        "expected_tools": ["get_user_profile"],
        "status_tag": "✅",
    },

    # === S2: 数据采集（需要 Getjob 服务）===
    {
        "id": "S2-1",
        "name": "platform_status",
        "message": "查看猎聘平台的当前状态",
        "expected_tools": ["platform_status"],
        "status_tag": "🔧",
    },

    # === S3: 知识检索 ===
    {
        "id": "S3-1",
        "name": "query_jobs",
        "message": "帮我查询数据库中上海的岗位",
        "expected_tools": ["query_jobs"],
        "status_tag": "✅",
    },
    {
        "id": "S3-2",
        "name": "rag_query",
        "message": "用知识图谱搜索 AI Agent 相关的岗位信息",
        "expected_tools": ["rag_query"],
        "status_tag": "✅",
    },

    # === S6: 进度追踪 ===
    {
        "id": "S6-1",
        "name": "get_stats",
        "message": "查看我的投递统计数据",
        "expected_tools": ["get_stats"],
        "status_tag": "✅",
    },
    {
        "id": "S6-2",
        "name": "job_count",
        "message": "数据库里现在有多少条岗位数据？",
        "expected_tools": ["job_count"],
        "status_tag": "✅",
    },
]


async def run_test(client: httpx.AsyncClient, scenario: dict) -> dict:
    sid = scenario["id"]
    name = scenario["name"]
    print(f"\n{'='*60}")
    print(f"[{sid}] {name} ({scenario['status_tag']})")
    print(f"  消息: {scenario['message']}")

    start = time.time()
    try:
        resp = await client.post(
            f"{BASE}/api/test/chat",
            json={"message": scenario["message"]},
            timeout=TIMEOUT,
        )
        elapsed = int((time.time() - start) * 1000)

        if resp.status_code != 200:
            print(f"  ❌ HTTP {resp.status_code}: {resp.text[:200]}")
            return {"id": sid, "name": name, "pass": False, "reason": f"HTTP {resp.status_code}", "ms": elapsed}

        data = resp.json()
        if not data.get("ok"):
            print(f"  ❌ API error: {data.get('error', 'unknown')}")
            return {"id": sid, "name": name, "pass": False, "reason": data.get("error", "unknown"), "ms": elapsed}

        # 检查 tool 调用
        called_tools = [tc["name"] for tc in data.get("tool_calls", [])]
        expected = scenario["expected_tools"]
        matched = any(t in called_tools for t in expected)

        # 检查 tool 执行是否成功
        tool_results = []
        for tc in data.get("tool_calls", []):
            tool_results.append({
                "tool": tc["name"],
                "success": tc.get("success", False),
                "ms": tc.get("duration_ms", 0),
            })

        all_success = all(tc.get("success", False) for tc in data.get("tool_calls", []) if tc["name"] in expected)

        passed = matched and all_success
        status = "✅" if passed else "❌"

        print(f"  {status} 调用工具: {called_tools}")
        print(f"  期望工具: {expected} | 匹配: {matched} | 执行成功: {all_success}")
        print(f"  回复: {(data.get('reply') or '')[:120]}")
        print(f"  耗时: {elapsed}ms (LLM+Tool)")

        for tr in tool_results:
            s = "✅" if tr["success"] else "❌"
            print(f"    {s} {tr['tool']} ({tr['ms']}ms)")

        reason = "" if passed else f"expected {expected}, got {called_tools}, success={all_success}"
        return {"id": sid, "name": name, "pass": passed, "reason": reason, "ms": elapsed, "tools_called": called_tools}

    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        print(f"  ❌ Exception: {e}")
        return {"id": sid, "name": name, "pass": False, "reason": str(e), "ms": elapsed}


async def main():
    # 先检查服务
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{BASE}/api/health", timeout=5)
            if r.status_code != 200:
                print("❌ OfferBot 服务未响应"); sys.exit(1)
        except Exception:
            print("❌ 无法连接 OfferBot (localhost:7860)"); sys.exit(1)

        try:
            r = await client.get("http://localhost:8888/api/health", timeout=5)
            print(f"✅ Getjob 服务: {r.json().get('status', 'unknown')}")
        except Exception:
            print("⚠️  Getjob 服务未运行，S2 测试可能失败")

        print(f"\n开始测试 {len(SCENARIOS)} 个场景...\n")

        results = []
        for scenario in SCENARIOS:
            result = await run_test(client, scenario)
            results.append(result)

    # 汇总
    print(f"\n{'='*60}")
    print("测试汇总")
    print(f"{'='*60}")
    passed = sum(1 for r in results if r["pass"])
    failed = sum(1 for r in results if not r["pass"])
    print(f"通过: {passed}/{len(results)}  失败: {failed}/{len(results)}\n")

    for r in results:
        s = "✅" if r["pass"] else "❌"
        extra = f" — {r['reason']}" if r.get("reason") else ""
        print(f"  {s} [{r['id']}] {r['name']} ({r['ms']}ms){extra}")

    if failed:
        print(f"\n⚠️  {failed} 个测试未通过")
        sys.exit(1)
    else:
        print("\n🎉 全部通过！")


if __name__ == "__main__":
    asyncio.run(main())
