#!/usr/bin/env python3
"""
真实测试 Getjob 相关的 🔧 方法（需要 Getjob 服务运行）。
platform_start_task, platform_stop_task, sync_jobs, save_application
"""
import asyncio
import sys
import time

import httpx

BASE = "http://localhost:7860"
TIMEOUT = 120

SCENARIOS = [
    # sync_jobs — 从 getjob 同步岗位到本地
    {
        "id": "G-1",
        "name": "sync_jobs",
        "message": "从猎聘平台同步岗位数据到本地数据库",
        "expected_tools": ["sync_jobs"],
    },
    # save_application — 保存投递记录
    {
        "id": "G-2",
        "name": "save_application",
        "message": "帮我记录一下，我刚投递了岗位 ID 1，平台是猎聘",
        "expected_tools": ["save_application"],
    },
    # platform_start_task + platform_stop_task — 启动然后停止爬取
    {
        "id": "G-3",
        "name": "platform_start_task",
        "message": "在猎聘上启动岗位搜索任务",
        "expected_tools": ["platform_start_task"],
    },
    {
        "id": "G-4",
        "name": "platform_stop_task",
        "message": "停止猎聘平台当前正在运行的任务",
        "expected_tools": ["platform_stop_task"],
    },
]


async def run_test(client: httpx.AsyncClient, scenario: dict) -> dict:
    sid = scenario["id"]
    name = scenario["name"]
    print(f"\n{'='*60}")
    print(f"[{sid}] {name}")
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
            return {"id": sid, "name": name, "pass": False, "reason": data.get("error"), "ms": elapsed}

        called_tools = [tc["name"] for tc in data.get("tool_calls", [])]
        expected = scenario["expected_tools"]
        matched = any(t in called_tools for t in expected)
        all_success = all(tc.get("success", False) for tc in data.get("tool_calls", []) if tc["name"] in expected)
        passed = matched and all_success
        status = "✅" if passed else "❌"

        print(f"  {status} 调用工具: {called_tools}")
        print(f"  期望工具: {expected} | 匹配: {matched} | 执行成功: {all_success}")
        print(f"  回复: {(data.get('reply') or '')[:200]}")
        print(f"  耗时: {elapsed}ms")

        for tc in data.get("tool_calls", []):
            s = "✅" if tc["success"] else "❌"
            print(f"    {s} {tc['name']} ({tc['duration_ms']}ms)")
            if not tc["success"]:
                print(f"       结果: {tc.get('result', '')[:200]}")

        reason = "" if passed else f"expected {expected}, got {called_tools}, success={all_success}"
        return {"id": sid, "name": name, "pass": passed, "reason": reason, "ms": elapsed}

    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        print(f"  ❌ Exception: {e}")
        return {"id": sid, "name": name, "pass": False, "reason": str(e), "ms": elapsed}


async def main():
    async with httpx.AsyncClient() as client:
        # 检查服务
        for url, label in [(f"{BASE}/api/health", "OfferBot"), ("http://localhost:8888/api/health", "Getjob")]:
            try:
                r = await client.get(url, timeout=5)
                print(f"✅ {label}: OK")
            except Exception:
                print(f"❌ {label} 未运行"); sys.exit(1)

        results = []
        for scenario in SCENARIOS:
            result = await run_test(client, scenario)
            results.append(result)
            # G-3 启动任务后等一下再停止
            if scenario["id"] == "G-3":
                await asyncio.sleep(2)

    print(f"\n{'='*60}")
    print("测试汇总")
    print(f"{'='*60}")
    passed = sum(1 for r in results if r["pass"])
    for r in results:
        s = "✅" if r["pass"] else "❌"
        extra = f" — {r['reason']}" if r.get("reason") else ""
        print(f"  {s} [{r['id']}] {r['name']} ({r['ms']}ms){extra}")
    print(f"\n通过: {passed}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())
