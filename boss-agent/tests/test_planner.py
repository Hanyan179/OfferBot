"""
Planner 模块单元测试

测试 Planner 的计划生成、响应解析、步骤校验逻辑。
LLM 调用通过 mock 替代。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agent.planner import Planner
from agent.state import AgentState, ExecutionPlan, Message, PlanStep, ErrorRecord
from agent.tool_registry import Tool, ToolRegistry


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class FakeTool(Tool):
    def __init__(self, name: str, desc: str = "fake"):
        self._name = name
        self._desc = desc

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._desc

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, params: dict, context: Any) -> Any:
        return {}


def _make_registry(*tool_names: str) -> ToolRegistry:
    reg = ToolRegistry()
    for n in tool_names:
        reg.register(FakeTool(n, f"Tool {n}"))
    return reg


# ---------------------------------------------------------------------------
# Tests: _parse_plan_response
# ---------------------------------------------------------------------------

class TestParsePlanResponse:
    def setup_method(self):
        self.planner = Planner(api_key="test", tool_registry=_make_registry("save_job"))

    def test_valid_json(self):
        raw = json.dumps({
            "steps": [
                {
                    "description": "保存岗位",
                    "tool_name": "save_job",
                    "tool_args": {"url": "https://example.com"},
                    "depends_on": [],
                }
            ]
        })
        steps = self.planner._parse_plan_response(raw)
        assert len(steps) == 1
        assert steps[0].tool_name == "save_job"
        assert steps[0].tool_args == {"url": "https://example.com"}

    def test_json_with_code_fences(self):
        raw = '```json\n{"steps": [{"description": "d", "tool_name": "save_job", "tool_args": {}, "depends_on": []}]}\n```'
        steps = self.planner._parse_plan_response(raw)
        assert len(steps) == 1

    def test_invalid_json_returns_empty(self):
        steps = self.planner._parse_plan_response("not json at all")
        assert steps == []

    def test_empty_steps(self):
        raw = json.dumps({"steps": []})
        steps = self.planner._parse_plan_response(raw)
        assert steps == []

    def test_missing_fields_use_defaults(self):
        raw = json.dumps({"steps": [{"tool_name": "save_job"}]})
        steps = self.planner._parse_plan_response(raw)
        assert len(steps) == 1
        assert steps[0].description == ""
        assert steps[0].tool_args == {}
        assert steps[0].depends_on == []


# ---------------------------------------------------------------------------
# Tests: _validate_steps
# ---------------------------------------------------------------------------

class TestValidateSteps:
    def test_filters_unregistered_tools(self):
        planner = Planner(api_key="test", tool_registry=_make_registry("save_job", "get_stats"))
        steps = [
            PlanStep("save", "save_job", {}, []),
            PlanStep("unknown", "nonexistent_tool", {}, []),
            PlanStep("stats", "get_stats", {}, [0]),
        ]
        valid = planner._validate_steps(steps)
        assert len(valid) == 2
        assert valid[0].tool_name == "save_job"
        assert valid[1].tool_name == "get_stats"

    def test_no_registry_returns_all(self):
        planner = Planner(api_key="test", tool_registry=None)
        steps = [PlanStep("x", "anything", {}, [])]
        assert planner._validate_steps(steps) == steps

    def test_all_valid(self):
        planner = Planner(api_key="test", tool_registry=_make_registry("a", "b"))
        steps = [PlanStep("s1", "a", {}, []), PlanStep("s2", "b", {}, [0])]
        assert planner._validate_steps(steps) == steps


# ---------------------------------------------------------------------------
# Tests: plan() with mocked LLM
# ---------------------------------------------------------------------------

class TestPlan:
    @pytest.mark.asyncio
    async def test_plan_returns_execution_plan(self):
        registry = _make_registry("save_job", "get_stats")
        planner = Planner(api_key="test", tool_registry=registry)

        mock_response = json.dumps({
            "steps": [
                {"description": "保存岗位", "tool_name": "save_job", "tool_args": {"url": "http://x"}, "depends_on": []},
                {"description": "查看统计", "tool_name": "get_stats", "tool_args": {}, "depends_on": [0]},
            ]
        })

        with patch.object(planner, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            plan = await planner.plan("搜索并统计岗位")

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 2
        assert plan.original_input == "搜索并统计岗位"
        assert plan.steps[0].tool_name == "save_job"
        assert plan.steps[1].tool_name == "get_stats"

    @pytest.mark.asyncio
    async def test_plan_filters_invalid_tools(self):
        registry = _make_registry("save_job")
        planner = Planner(api_key="test", tool_registry=registry)

        mock_response = json.dumps({
            "steps": [
                {"description": "s1", "tool_name": "save_job", "tool_args": {}, "depends_on": []},
                {"description": "s2", "tool_name": "ghost_tool", "tool_args": {}, "depends_on": []},
            ]
        })

        with patch.object(planner, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            plan = await planner.plan("test")

        assert len(plan.steps) == 1
        assert plan.steps[0].tool_name == "save_job"

    @pytest.mark.asyncio
    async def test_plan_with_context(self):
        registry = _make_registry("save_job")
        planner = Planner(api_key="test", tool_registry=registry)

        mock_response = json.dumps({
            "steps": [{"description": "s", "tool_name": "save_job", "tool_args": {}, "depends_on": []}]
        })

        with patch.object(planner, "_call_llm", new_callable=AsyncMock, return_value=mock_response) as mock_llm:
            await planner.plan("test", context={"city": "上海"})
            # Verify context was included in the LLM call
            call_args = mock_llm.call_args[0][0]
            assert any("上海" in msg["content"] for msg in call_args)


# ---------------------------------------------------------------------------
# Tests: replan() with mocked LLM
# ---------------------------------------------------------------------------

class TestReplan:
    @pytest.mark.asyncio
    async def test_replan_generates_new_plan(self):
        registry = _make_registry("get_stats")
        planner = Planner(api_key="test", tool_registry=registry)

        state = AgentState(
            messages=(Message(role="user", content="原始指令"),),
            current_step=1,
            intermediate_results={"save_job": {"job_id": 1}},
            errors=(ErrorRecord(
                timestamp=datetime.now(),
                step_index=1,
                tool_name="parse_jd",
                error_type="api_error",
                error_message="timeout",
                retry_count=3,
                resolved=False,
            ),),
            turn_count=2,
        )

        mock_response = json.dumps({
            "steps": [{"description": "重新统计", "tool_name": "get_stats", "tool_args": {}, "depends_on": []}]
        })

        with patch.object(planner, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
            plan = await planner.replan(state, "parse_jd 超时")

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 1
        assert plan.original_input == "原始指令"


# ---------------------------------------------------------------------------
# Tests: _get_available_tools_description
# ---------------------------------------------------------------------------

class TestAvailableToolsDescription:
    def test_no_registry(self):
        planner = Planner(api_key="test", tool_registry=None)
        assert "(无可用 Tool)" in planner._get_available_tools_description()

    def test_empty_registry(self):
        planner = Planner(api_key="test", tool_registry=ToolRegistry())
        assert "(无可用 Tool)" in planner._get_available_tools_description()

    def test_with_tools(self):
        planner = Planner(api_key="test", tool_registry=_make_registry("save_job", "get_stats"))
        desc = planner._get_available_tools_description()
        assert "save_job" in desc
        assert "get_stats" in desc
