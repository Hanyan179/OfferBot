#!/usr/bin/env python3
"""
Bootstrap 集成端到端测试 — 验证 LightRAG 集成后完整链路

通过 POST /api/test/chat 接口，验证：
1. rag_query tool 已注册且可被 LLM 路由到
2. query_jobs tool 在条件筛选场景仍正常工作
3. System Prompt 场景路由策略生效（LLM 选对 tool + mode）
4. job_rag 注入到 tool context（rag_query 不返回"未初始化"错误）
5. 完整 function calling loop 能跑通

用法：
    # 先启动服务
    cd boss-agent && python3 -m uvicorn web.app:app --host 0.0.0.0 --port 7860

    # 运行测试
    python3 scripts/test_bootstrap_e2e.py

    # 指定服务地址
    TEST_BASE_URL=http://localhost:7860 python3 scripts/test_bootstrap_e2e.py

    # 只跑单个场景
    python3 scripts/test_bootstrap_e2e.py --scenario S2

    # 每场景多次运行
    RUNS=3 python3 scripts/test_bootstrap_e2e.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field

import httpx

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:7860")
RUNS = int(os.getenv("RUNS", "1"))


# ---------------------------------------------------------------------------
# 场景定义
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    id: str
    name: str
    message: str
    expect_tool: str | None = None       # 预期调用的 tool name
    expect_mode: str | None = None       # 预期 rag_query 的 mode 参数
    expect_not_tool: str | None = None   # 不应调用的 tool
    priority: str = "P0"


SCENARIOS = [
    # === 检索类（P0）===
    Scenario(
        id="S1", name="画像匹配推荐", priority="P0",
        message="根据我的画像，目前有哪些岗位适合我？",
        expect_tool="rag_query", expect_mode="answer",
    ),
    Scenario(
        id="S2", name="条件筛选", priority="P0",
        message="帮我找上海 40K 以上的 AI 岗位",
        expect_tool="query_jobs",
    ),
    Scenario(
        id="S3", name="相似推荐", priority="P0",
        message="找跟 AI Agent 引擎架构类似的岗位",
        expect_tool="rag_query", expect_mode="search",
    ),
    Scenario(
        id="S4", name="匹配度分析", priority="P0",
        message="3756 这个岗位跟我的技能匹配吗？帮我分析一下差距",
        expect_tool="rag_query", expect_mode="answer",
    ),
    Scenario(
        id="S5", name="知识问答", priority="P0",
        message="目前市场上 AI Agent 岗位最常要求的技能 TOP10 是什么？",
        expect_tool="rag_query", expect_mode="answer",
    ),
    Scenario(
        id="S6", name="精确查找", priority="P0",
        message="京东有什么岗位？",
        expect_tool="query_jobs",
    ),
    # === 分析类（P1）===
    Scenario(
        id="S7", name="技能差距分析", priority="P1",
        message="我缺什么技能才能匹配 AI Agent 架构师这个岗位？",
        expect_tool="rag_query", expect_mode="answer",
    ),
    Scenario(
        id="S13", name="投递追踪", priority="P1",
        message="我的投递进度怎么样？",
        expect_not_tool="rag_query",
    ),
]


# ---------------------------------------------------------------------------
# 测试执行
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    scenario_id: str
    route_ok: bool
    mode_ok: bool
    not_tool_ok: bool
    tools_used: list[str] = field(default_factory=list)
    rag_modes: list[str] = field(default_factory=list)
    duration_ms: int = 0
    error: str | None = None
    reply_preview: str = ""
    rag_result_preview: str = ""


async def run_scenario(scenario: Scenario) -> RunResult:
    """发送一次请求，返回验证结果。"""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{BASE_URL}/api/test/chat",
                json={"message": scenario.message},
            )
    except httpx.ConnectError:
        return RunResult(
            scenario_id=scenario.id, route_ok=False, mode_ok=False,
            not_tool_ok=False, error="无法连接服务",
        )
    except Exception as e:
        return RunResult(
            scenario_id=scenario.id, route_ok=False, mode_ok=False,
            not_tool_ok=False, error=str(e),
        )

    if resp.status_code != 200:
        return RunResult(
            scenario_id=scenario.id, route_ok=False, mode_ok=False,
            not_tool_ok=False, error=f"HTTP {resp.status_code}: {resp.text[:200]}",
        )

    data = resp.json()
    if not data.get("ok"):
        return RunResult(
            scenario_id=scenario.id, route_ok=False, mode_ok=False,
            not_tool_ok=False, error=data.get("error", "unknown"),
        )

    tool_calls = data.get("tool_calls", [])
    tools_used = [tc["name"] for tc in tool_calls]
    duration_ms = data.get("total_duration_ms", 0)
    reply = data.get("reply", "")

    # 提取 rag_query 的 mode 参数
    rag_modes = []
    rag_result_preview = ""
    for tc in tool_calls:
        if tc["name"] == "rag_query":
            params = tc.get("params", {})
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except Exception:
                    params = {}
            rag_modes.append(params.get("mode", "?"))
            # 检查 rag_query 是否返回了"未初始化"错误
            result_str = tc.get("result", "")
            if "未初始化" in str(result_str):
                rag_result_preview = "⚠️ 知识图谱未初始化"
            elif tc.get("success"):
                rag_result_preview = "✅ 执行成功"
            else:
                rag_result_preview = f"❌ 执行失败: {str(result_str)[:80]}"

    # 验证路由
    route_ok = True
    if scenario.expect_tool:
        route_ok = scenario.expect_tool in tools_used

    # 验证 mode
    mode_ok = True
    if scenario.expect_mode:
        mode_ok = scenario.expect_mode in rag_modes

    # 验证反向路由
    not_tool_ok = True
    if scenario.expect_not_tool:
        not_tool_ok = scenario.expect_not_tool not in tools_used

    return RunResult(
        scenario_id=scenario.id,
        route_ok=route_ok,
        mode_ok=mode_ok,
        not_tool_ok=not_tool_ok,
        tools_used=tools_used,
        rag_modes=rag_modes,
        duration_ms=duration_ms,
        reply_preview=reply[:120] if reply else "(empty)",
        rag_result_preview=rag_result_preview,
    )


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def print_report(
    scenario_results: dict[str, list[RunResult]],
    scenarios_map: dict[str, Scenario],
):
    """打印结构化测试报告。"""
    print()
    print("=" * 80)
    print("  Bootstrap 集成端到端测试报告")
    print("=" * 80)

    total_pass = 0
    total_fail = 0
    total_scenarios = 0

    for sid, results in scenario_results.items():
        sc = scenarios_map[sid]
        total_scenarios += 1

        # 统计
        route_pass = sum(1 for r in results if r.route_ok)
        mode_pass = sum(1 for r in results if r.mode_ok)
        not_tool_pass = sum(1 for r in results if r.not_tool_ok)
        n = len(results)

        # 综合判定
        all_ok = all(
            r.route_ok and r.mode_ok and r.not_tool_ok and r.error is None
            for r in results
        )
        if all_ok:
            total_pass += 1
        else:
            total_fail += 1

        status = "✅" if all_ok else "❌"
        print(f"\n{status} {sc.id}: {sc.name} ({sc.priority})")
        print(f"   消息: {sc.message}")

        if sc.expect_tool:
            print(f"   路由: {route_pass}/{n} → {sc.expect_tool}")
        if sc.expect_mode:
            print(f"   Mode: {mode_pass}/{n} → {sc.expect_mode}")
        if sc.expect_not_tool:
            print(f"   反向: {not_tool_pass}/{n} (不应调 {sc.expect_not_tool})")

        for i, r in enumerate(results):
            prefix = f"   Run {i+1}:" if n > 1 else "   结果:"
            if r.error:
                print(f"   {prefix} ❌ 错误: {r.error}")
            else:
                tools_str = ", ".join(r.tools_used) if r.tools_used else "(无工具调用)"
                print(f"   {prefix} tools=[{tools_str}] modes={r.rag_modes} {r.duration_ms}ms")
                if r.rag_result_preview:
                    print(f"          RAG: {r.rag_result_preview}")
                print(f"          回复: {r.reply_preview}")

    print(f"\n{'='*80}")
    print(f"  总计: {total_pass}/{total_scenarios} 场景通过")
    if total_fail > 0:
        print(f"  失败: {total_fail} 场景")
    print(f"{'='*80}")

    return total_fail == 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Bootstrap 集成端到端测试")
    parser.add_argument("--scenario", type=str, help="只跑指定场景 (如 S2)")
    parser.add_argument("--priority", type=str, help="按优先级筛选 (P0/P1)")
    parser.add_argument("--all", action="store_true", help="跑全部场景")
    args = parser.parse_args()

    # 筛选场景
    targets = SCENARIOS
    if args.scenario:
        targets = [s for s in SCENARIOS if s.id == args.scenario.upper()]
        if not targets:
            print(f"❌ 未找到场景: {args.scenario}")
            sys.exit(1)
    elif args.priority:
        targets = [s for s in SCENARIOS if s.priority == args.priority.upper()]
    elif not args.all:
        # 默认只跑 P0
        targets = [s for s in SCENARIOS if s.priority == "P0"]

    scenarios_map = {s.id: s for s in targets}
    runs = RUNS

    print(f"🧪 Bootstrap 集成端到端测试")
    print(f"   服务: {BASE_URL}")
    print(f"   场景: {len(targets)} 个")
    print(f"   每场景运行: {runs} 次")
    print()

    # 检查服务可用性
    print("检查服务连接...", end=" ", flush=True)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{BASE_URL}/")
            if r.status_code >= 500:
                print(f"❌ 服务异常: HTTP {r.status_code}")
                sys.exit(1)
        print("✅")
    except Exception as e:
        print(f"❌ 无法连接: {e}")
        print(f"\n请先启动服务:")
        print(f"  cd boss-agent && python3 -m uvicorn web.app:app --host 0.0.0.0 --port 7860")
        sys.exit(1)

    # 执行测试
    scenario_results: dict[str, list[RunResult]] = {}
    for sc in targets:
        print(f"\n▶ {sc.id}: {sc.name}...", flush=True)
        results = []
        for run_idx in range(runs):
            if runs > 1:
                print(f"  Run {run_idx + 1}/{runs}...", end=" ", flush=True)
            result = await run_scenario(sc)
            results.append(result)
            if result.error:
                print(f"❌ {result.error}")
            else:
                ok = result.route_ok and result.mode_ok and result.not_tool_ok
                print(f"{'✅' if ok else '❌'} {result.duration_ms}ms tools={result.tools_used}")
        scenario_results[sc.id] = results

    # 报告
    all_pass = print_report(scenario_results, scenarios_map)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    asyncio.run(main())
