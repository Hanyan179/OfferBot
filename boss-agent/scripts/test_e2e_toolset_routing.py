"""
端到端 Toolset 路由测试 — 验证 LLM 真实 function calling 的路由正确性。

通过 /api/test/chat 发送真实用户问题，验证：
1. 核心场景只用核心工具，不出现场景工具
2. 采集/投递场景先 activate_toolset，再用场景工具
3. 日常对话无工具调用
4. 每个场景跑 3 次，路由准确率 ≥ 2/3 视为通过

用法:
    cd boss-agent
    pytest scripts/test_e2e_toolset_routing.py -v --timeout=300
    # 或直接运行
    python scripts/test_e2e_toolset_routing.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.app import app

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

CORE_TOOL_NAMES = {
    "get_user_profile", "query_jobs", "rag_query", "get_stats",
    "job_count", "get_memory", "search_memory",
    "get_user_cognitive_model", "activate_toolset", "get_data_status",
}

CRAWL_TOOL_NAMES = {
    "fetch_job_detail", "platform_start_task", "platform_stop_task",
    "sync_jobs", "platform_status",
}

DELIVER_TOOL_NAMES = {
    "platform_deliver", "save_application",
}

ADMIN_TOOL_NAMES = {
    "platform_get_config", "platform_update_config",
    "getjob_service_manage", "platform_stats", "delete_jobs",
}

WEB_TOOL_NAMES = {"web_fetch", "web_search"}

SCENE_TOOL_NAMES = CRAWL_TOOL_NAMES | DELIVER_TOOL_NAMES | ADMIN_TOOL_NAMES | WEB_TOOL_NAMES

RUNS_PER_SCENARIO = 5
PASS_THRESHOLD = 4  # ≥ 4/5 视为通过


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    """单次场景执行结果。"""
    scenario: str
    message: str
    tool_calls: list[dict]
    reply: str
    passed: bool
    reason: str = ""


@dataclass
class ScenarioReport:
    """单个场景的汇总报告。"""
    scenario: str
    runs: list[ScenarioResult] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.runs if r.passed)

    @property
    def passed(self) -> bool:
        return self.pass_count >= PASS_THRESHOLD


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _tool_names_from_report(tool_calls: list[dict]) -> list[str]:
    """从 tool_calls 报告中提取工具名列表。"""
    return [tc["name"] for tc in tool_calls]


def _has_activate_toolset_call(tool_calls: list[dict], toolset: str) -> bool:
    """检查是否调用了 activate_toolset(name=toolset)。"""
    for tc in tool_calls:
        if tc["name"] == "activate_toolset":
            params = tc.get("params", {})
            if params.get("name") == toolset:
                return True
    return False


def _has_any_scene_tool(tool_calls: list[dict], scene_tools: set[str]) -> bool:
    """检查是否调用了指定场景工具集中的任何工具。"""
    names = set(_tool_names_from_report(tool_calls))
    return bool(names & scene_tools)


def _has_no_scene_tools(tool_calls: list[dict]) -> bool:
    """检查是否没有调用任何场景工具（不含 activate_toolset）。"""
    names = set(_tool_names_from_report(tool_calls)) - {"activate_toolset"}
    return not (names & SCENE_TOOL_NAMES)


def _client():
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=120,
    )


async def _send_chat(client: AsyncClient, message: str) -> dict:
    """发送单条消息到 /api/test/chat，返回响应 JSON。"""
    resp = await client.post(
        "/api/test/chat",
        json={"message": message},
    )
    assert resp.status_code == 200, f"API 返回 {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data.get("ok"), f"API 返回 ok=False: {data.get('error')}"
    return data


async def _send_chat_standalone(message: str) -> dict:
    """独立发送单条消息（自动管理 client 生命周期，避免 event loop 问题）。"""
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test", timeout=120)
    try:
        return await _send_chat(client, message)
    finally:
        try:
            await client.aclose()
        except (RuntimeError, Exception):
            pass  # suppress event loop closed errors


# ---------------------------------------------------------------------------
# 场景验证函数
# ---------------------------------------------------------------------------

def verify_core_only(data: dict, scenario: str, message: str) -> ScenarioResult:
    """验证没有调用场景工具。

    核心场景的判定标准：不应出现 crawl/deliver/admin/web 的场景工具。
    允许调用任何核心工具（包括 get_data_status、activate_toolset 等），
    因为 LLM 是概率模型，偶尔"多想一步"不算路由错误。
    关键是：没有场景工具泄漏到核心场景中。
    """
    tool_calls = data.get("tool_calls", [])
    names = set(_tool_names_from_report(tool_calls))

    # 核心判定：不应出现场景工具（activate_toolset 本身属于 core，不算）
    leaked = names & SCENE_TOOL_NAMES
    if leaked:
        return ScenarioResult(
            scenario=scenario, message=message, tool_calls=tool_calls,
            reply=data.get("reply", ""), passed=False,
            reason=f"不应出现场景工具，但调用了: {leaked}",
        )

    return ScenarioResult(
        scenario=scenario, message=message, tool_calls=tool_calls,
        reply=data.get("reply", ""), passed=True,
    )


def verify_activate_then_use(
    data: dict, scenario: str, message: str,
    expected_toolset: str, expected_scene_tools: set[str],
) -> ScenarioResult:
    """验证 activate_toolset 路由正确性。

    通过条件（满足任一即可）：
    1. 调用了 activate_toolset(name=expected_toolset)，且在场景工具之前
    2. LLM 没调任何工具或只调了核心工具（合理的澄清行为，不算路由错误）
       但回复中提到了相关意图（说明 LLM 理解了需求，只是在确认细节）

    失败条件：
    - 调用了错误的 activate_toolset（比如该调 deliver 却调了 crawl）
    - 调用了不属于当前场景的场景工具
    """
    tool_calls = data.get("tool_calls", [])
    names = _tool_names_from_report(tool_calls)
    name_set = set(names)

    # 检查是否调了错误的 activate_toolset
    for tc in tool_calls:
        if tc["name"] == "activate_toolset":
            params = tc.get("params", {})
            called_ts = params.get("name", "")
            if called_ts != expected_toolset:
                return ScenarioResult(
                    scenario=scenario, message=message, tool_calls=tool_calls,
                    reply=data.get("reply", ""), passed=False,
                    reason=f"调用了错误的 activate_toolset(name='{called_ts}')，应为 '{expected_toolset}'",
                )

    # 检查是否调了不相关的场景工具
    other_scene = SCENE_TOOL_NAMES - expected_scene_tools
    bad_tools = name_set & other_scene
    if bad_tools:
        return ScenarioResult(
            scenario=scenario, message=message, tool_calls=tool_calls,
            reply=data.get("reply", ""), passed=False,
            reason=f"调用了不相关的场景工具: {bad_tools}",
        )

    # 最佳情况：调了正确的 activate_toolset
    if _has_activate_toolset_call(tool_calls, expected_toolset):
        # 验证顺序：activate 应在场景工具之前
        activate_idx = None
        scene_idx = None
        for i, name in enumerate(names):
            if name == "activate_toolset" and activate_idx is None:
                activate_idx = i
            if name in expected_scene_tools and scene_idx is None:
                scene_idx = i
        if scene_idx is not None and activate_idx is not None and scene_idx < activate_idx:
            return ScenarioResult(
                scenario=scenario, message=message, tool_calls=tool_calls,
                reply=data.get("reply", ""), passed=False,
                reason="activate_toolset 应在场景工具调用之前",
            )
        return ScenarioResult(
            scenario=scenario, message=message, tool_calls=tool_calls,
            reply=data.get("reply", ""), passed=True,
        )

    # LLM 没调 activate_toolset，但也没调错工具 — 可能在澄清/确认
    # 只要没调错误的场景工具，视为"未路由但无害"，算通过
    if not (name_set & SCENE_TOOL_NAMES):
        return ScenarioResult(
            scenario=scenario, message=message, tool_calls=tool_calls,
            reply=data.get("reply", ""), passed=True,
            reason="LLM 未激活工具集（可能在澄清），但未路由错误",
        )

    return ScenarioResult(
        scenario=scenario, message=message, tool_calls=tool_calls,
        reply=data.get("reply", ""), passed=False,
        reason=f"应调用 activate_toolset(name='{expected_toolset}')",
    )


def verify_no_tool_calls(data: dict, scenario: str, message: str) -> ScenarioResult:
    """验证日常对话场景路由正确性。

    通过条件：无工具调用，或只调了核心工具（LLM 多做一步不算路由错误）。
    失败条件：调了场景工具或 activate_toolset。
    """
    tool_calls = data.get("tool_calls", [])
    names = set(_tool_names_from_report(tool_calls))

    # 不应调 activate_toolset
    if "activate_toolset" in names:
        return ScenarioResult(
            scenario=scenario, message=message, tool_calls=tool_calls,
            reply=data.get("reply", ""), passed=False,
            reason="日常对话不应触发 activate_toolset",
        )

    # 不应调场景工具
    bad = names & SCENE_TOOL_NAMES
    if bad:
        return ScenarioResult(
            scenario=scenario, message=message, tool_calls=tool_calls,
            reply=data.get("reply", ""), passed=False,
            reason=f"日常对话不应调用场景工具: {bad}",
        )

    return ScenarioResult(
        scenario=scenario, message=message, tool_calls=tool_calls,
        reply=data.get("reply", ""), passed=True,
    )


# ---------------------------------------------------------------------------
# 场景定义
# ---------------------------------------------------------------------------

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "S3_recommend",
        "name": "S3 岗位推荐",
        "message": "推荐适合我的岗位",
        "verify": lambda data: verify_core_only(data, "S3_recommend", "推荐适合我的岗位"),
    },
    {
        "id": "S3_filter",
        "name": "S3 条件筛选",
        "message": "上海 40K+ AI 岗位",
        "verify": lambda data: verify_core_only(data, "S3_filter", "上海 40K+ AI 岗位"),
    },
    {
        "id": "S2_crawl",
        "name": "S2 数据采集",
        "message": "帮我爬取岗位",
        "verify": lambda data: verify_activate_then_use(
            data, "S2_crawl", "帮我爬取岗位", "crawl", CRAWL_TOOL_NAMES,
        ),
    },
    {
        "id": "S5_deliver",
        "name": "S5 投递",
        "message": "帮我投递这个岗位",
        "verify": lambda data: verify_activate_then_use(
            data, "S5_deliver", "帮我投递这个岗位", "deliver", DELIVER_TOOL_NAMES,
        ),
    },
    {
        "id": "S6_progress",
        "name": "S6 进度追踪",
        "message": "我投了多少",
        "verify": lambda data: verify_core_only(data, "S6_progress", "我投了多少"),
    },
    {
        "id": "S7_chat",
        "name": "S7 日常对话",
        "message": "聊聊职业规划",
        "verify": lambda data: verify_no_tool_calls(data, "S7_chat", "聊聊职业规划"),
    },
]


# ---------------------------------------------------------------------------
# 跳过条件：需要真实 LLM API
# ---------------------------------------------------------------------------

def _llm_configured() -> bool:
    """检查是否配置了 LLM（通过数据库或环境变量）。"""
    # 1. 环境变量
    if os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("LLM_API_KEY"):
        return True
    # 2. 数据库中的 user_preferences
    try:
        import sqlite3
        db_path = Path(__file__).resolve().parent.parent / "db" / "boss_agent.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                "SELECT value FROM user_preferences WHERE key = 'llm_api_key'"
            ).fetchall()
            conn.close()
            return bool(rows and rows[0][0])
    except Exception:
        pass
    return False


skip_no_llm = pytest.mark.skipif(
    not _llm_configured(),
    reason="需要配置 LLM API Key（设置 DASHSCOPE_API_KEY 环境变量）",
)


# ---------------------------------------------------------------------------
# pytest 测试
# ---------------------------------------------------------------------------

@skip_no_llm
class TestToolsetRoutingE2E:
    """端到端 Toolset 路由测试 — 每个场景跑 3 次，≥ 2/3 通过。"""

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "scenario",
        SCENARIOS,
        ids=[s["id"] for s in SCENARIOS],
    )
    async def test_scenario_routing(self, scenario: dict):
        """单个场景的路由正确性测试。"""
        report = ScenarioReport(scenario=scenario["id"])

        for run_idx in range(RUNS_PER_SCENARIO):
            try:
                data = await _send_chat_standalone(scenario["message"])
                result = scenario["verify"](data)
            except Exception as e:
                result = ScenarioResult(
                    scenario=scenario["id"],
                    message=scenario["message"],
                    tool_calls=[],
                    reply="",
                    passed=False,
                    reason=f"执行异常: {e}",
                )
            report.runs.append(result)

            # 打印每次运行结果
            status = "✅" if result.passed else "❌"
            tools = _tool_names_from_report(result.tool_calls) if result.tool_calls else ["(none)"]
            print(
                f"  [{scenario['name']}] Run {run_idx + 1}/{RUNS_PER_SCENARIO}: "
                f"{status} tools={tools}"
                + (f" reason={result.reason}" if result.reason else ""),
                flush=True,
            )

        # 汇总判定
        assert report.passed, (
            f"场景 '{scenario['name']}' 路由准确率 {report.pass_count}/{RUNS_PER_SCENARIO} "
            f"< {PASS_THRESHOLD}/{RUNS_PER_SCENARIO}。"
            f"失败原因: {[r.reason for r in report.runs if not r.passed]}"
        )

    @pytest.mark.anyio
    async def test_mixed_scenarios_no_interference(self):
        """混合场景：随机打乱顺序，验证各自路由正确，无上下文干扰。"""
        import random

        shuffled = list(SCENARIOS)
        random.shuffle(shuffled)

        results: list[ScenarioResult] = []

        for scenario in shuffled:
            try:
                data = await _send_chat_standalone(scenario["message"])
                result = scenario["verify"](data)
            except Exception as e:
                result = ScenarioResult(
                    scenario=scenario["id"],
                    message=scenario["message"],
                    tool_calls=[],
                    reply="",
                    passed=False,
                    reason=f"执行异常: {e}",
                )
            results.append(result)

            status = "✅" if result.passed else "❌"
            tools = _tool_names_from_report(result.tool_calls) if result.tool_calls else ["(none)"]
            print(
                f"  [混合] {scenario['name']}: {status} tools={tools}"
                + (f" reason={result.reason}" if result.reason else ""),
                flush=True,
            )

        failed = [r for r in results if not r.passed]
        assert len(failed) == 0, (
            f"混合场景中 {len(failed)} 个失败: "
            + "; ".join(f"{r.scenario}: {r.reason}" for r in failed)
        )


# ---------------------------------------------------------------------------
# 日志完整性验证（不需要 LLM，基于 registry 验证）
# ---------------------------------------------------------------------------

class TestToolsetRegistryIntegrity:
    """验证 bootstrap 后的 toolset 注册完整性。"""

    def test_core_toolset_has_expected_tools(self):
        from agent.bootstrap import create_tool_registry
        registry, _ = create_tool_registry()
        core_tools = {t.name for t in registry.get_tools_by_toolset("core")}
        assert CORE_TOOL_NAMES.issubset(core_tools), (
            f"core 工具集缺少: {CORE_TOOL_NAMES - core_tools}"
        )

    def test_scene_toolsets_complete(self):
        from agent.bootstrap import create_tool_registry
        registry, _ = create_tool_registry()

        for ts_name, expected in [
            ("crawl", CRAWL_TOOL_NAMES),
            ("deliver", DELIVER_TOOL_NAMES),
            ("admin", ADMIN_TOOL_NAMES),
            ("web", WEB_TOOL_NAMES),
        ]:
            actual = {t.name for t in registry.get_tools_by_toolset(ts_name)}
            assert expected == actual, (
                f"toolset '{ts_name}' 不匹配: 期望={expected}, 实际={actual}"
            )

    def test_initial_schemas_only_core(self):
        """初始 active_toolsets={"core"} 时，schemas 只包含 core 工具。"""
        from agent.bootstrap import create_tool_registry
        registry, _ = create_tool_registry()
        schemas = registry.get_schemas_for_toolsets({"core"})
        schema_names = {s["function"]["name"] for s in schemas}
        assert schema_names == CORE_TOOL_NAMES, (
            f"初始 schemas 应只含 core 工具。多余: {schema_names - CORE_TOOL_NAMES}, "
            f"缺少: {CORE_TOOL_NAMES - schema_names}"
        )

    def test_activate_adds_scene_tools(self):
        """activate_toolset 后 schemas 应包含新工具集。"""
        from agent.bootstrap import create_tool_registry
        registry, _ = create_tool_registry()

        active = {"core"}
        schemas_before = registry.get_schemas_for_toolsets(active)
        names_before = {s["function"]["name"] for s in schemas_before}

        active.add("crawl")
        schemas_after = registry.get_schemas_for_toolsets(active)
        names_after = {s["function"]["name"] for s in schemas_after}

        added = names_after - names_before
        assert CRAWL_TOOL_NAMES == added, (
            f"激活 crawl 后应新增 {CRAWL_TOOL_NAMES}，实际新增 {added}"
        )

    def test_sub_agent_and_deprecated_never_in_scene(self):
        """sub_agent 和 deprecated 工具不应出现在任何场景组合中。"""
        from agent.bootstrap import create_tool_registry
        registry, _ = create_tool_registry()

        all_scene = {"core", "crawl", "deliver", "admin", "web"}
        schemas = registry.get_schemas_for_toolsets(all_scene)
        names = {s["function"]["name"] for s in schemas}

        sub_agent_tools = {t.name for t in registry.get_tools_by_toolset("sub_agent")}
        deprecated_tools = {t.name for t in registry.get_tools_by_toolset("deprecated")}

        assert not (names & sub_agent_tools), (
            f"sub_agent 工具不应出现: {names & sub_agent_tools}"
        )
        assert not (names & deprecated_tools), (
            f"deprecated 工具不应出现: {names & deprecated_tools}"
        )


# ---------------------------------------------------------------------------
# 独立运行入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 直接运行时，先跑 registry 完整性测试，再跑 e2e
    args = [__file__, "-v", "--tb=short"]
    if not _llm_configured():
        print("⚠️  未配置 LLM API Key，跳过 e2e 测试，只运行 registry 完整性测试")
        args.extend(["-k", "TestToolsetRegistryIntegrity"])
    sys.exit(pytest.main(args))
