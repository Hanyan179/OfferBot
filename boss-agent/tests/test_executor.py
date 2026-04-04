"""
Executor 模块单元测试

测试 ReAct Agent Loop、Tool 执行重试、状态更新逻辑。
LLM 调用和 Tool 执行通过 mock 替代。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agent.executor import Executor, Thought
from agent.state import (
    AgentEvent,
    AgentState,
    ExecutionPlan,
    Message,
    PlanStep,
    ToolCall,
    ToolResult,
)
from agent.tool_registry import Tool, ToolRegistry


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class SuccessTool(Tool):
    def __init__(self, name: str = "success_tool"):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Always succeeds"

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, params: dict, context: Any) -> dict:
        return {"result": "ok", "input": params}


class FailTool(Tool):
    """Fails N times then succeeds."""

    def __init__(self, name: str = "fail_tool", fail_count: int = 3):
        self._name = name
        self._fail_count = fail_count
        self._call_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Fails then succeeds"

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, params: dict, context: Any) -> dict:
        self._call_count += 1
        if self._call_count <= self._fail_count:
            raise RuntimeError(f"Fail #{self._call_count}")
        return {"result": "recovered"}


def _make_plan(*tool_names: str) -> ExecutionPlan:
    steps = tuple(
        PlanStep(description=f"Step {i}", tool_name=n, tool_args={}, depends_on=[])
        for i, n in enumerate(tool_names)
    )
    return ExecutionPlan(steps=steps, original_input="test input", created_at=datetime.now())


# ---------------------------------------------------------------------------
# Tests: _execute_tool
# ---------------------------------------------------------------------------

class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_success(self):
        reg = ToolRegistry()
        reg.register(SuccessTool("my_tool"))
        executor = Executor(api_key="test", tool_registry=reg)

        call = ToolCall(tool_name="my_tool", arguments={"x": 1})
        result = await executor._execute_tool(call, {}, max_retries=3)

        assert result.success is True
        assert "my_tool" in result.data
        assert result.data["my_tool"]["result"] == "ok"
        assert result.errors == ()

    @pytest.mark.asyncio
    async def test_tool_not_found(self):
        reg = ToolRegistry()
        executor = Executor(api_key="test", tool_registry=reg)

        call = ToolCall(tool_name="ghost", arguments={})
        result = await executor._execute_tool(call, {}, max_retries=1)

        assert result.success is False
        assert len(result.errors) == 1
        assert result.errors[0].error_type == "not_found"

    @pytest.mark.asyncio
    async def test_no_registry(self):
        executor = Executor(api_key="test", tool_registry=None)

        call = ToolCall(tool_name="any", arguments={})
        result = await executor._execute_tool(call, {}, max_retries=1)

        assert result.success is False
        assert result.errors[0].error_type == "config_error"

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self):
        reg = ToolRegistry()
        tool = FailTool("retry_tool", fail_count=2)
        reg.register(tool)
        executor = Executor(api_key="test", tool_registry=reg)

        call = ToolCall(tool_name="retry_tool", arguments={})
        # Use max_retries=3, tool fails 2 times then succeeds on 3rd
        result = await executor._execute_tool(call, {}, max_retries=3)

        assert result.success is True
        assert tool._call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        reg = ToolRegistry()
        tool = FailTool("always_fail", fail_count=10)
        reg.register(tool)
        executor = Executor(api_key="test", tool_registry=reg)

        call = ToolCall(tool_name="always_fail", arguments={})
        result = await executor._execute_tool(call, {}, max_retries=2)

        assert result.success is False
        assert len(result.errors) == 1
        assert result.errors[0].retry_count == 2
        assert tool._call_count == 2

    @pytest.mark.asyncio
    async def test_elapsed_time_recorded(self):
        reg = ToolRegistry()
        reg.register(SuccessTool("timed"))
        executor = Executor(api_key="test", tool_registry=reg)

        call = ToolCall(tool_name="timed", arguments={})
        result = await executor._execute_tool(call, {}, max_retries=1)

        assert result.success is True
        assert "_elapsed_seconds" in result.data["timed"]
        assert result.data["timed"]["_elapsed_seconds"] >= 0


# ---------------------------------------------------------------------------
# Tests: _parse_thought
# ---------------------------------------------------------------------------

class TestParseThought:
    def setup_method(self):
        self.executor = Executor(api_key="test")

    def test_call_tool_action(self):
        raw = json.dumps({
            "action": "call_tool",
            "reasoning": "需要保存岗位",
            "tool_name": "save_job",
            "tool_args": {"url": "http://x"},
        })
        thought = self.executor._parse_thought(raw, current_step=0, total_steps=3)
        assert thought.action == "call_tool"
        assert thought.tool_call is not None
        assert thought.tool_call.tool_name == "save_job"
        assert thought.next_step == 1

    def test_finish_action(self):
        raw = json.dumps({"action": "finish", "reasoning": "所有步骤完成"})
        thought = self.executor._parse_thought(raw, current_step=2, total_steps=3)
        assert thought.action == "finish"
        assert thought.tool_call is None

    def test_invalid_json_defaults_to_finish(self):
        thought = self.executor._parse_thought("not json", current_step=0, total_steps=3)
        assert thought.action == "finish"

    def test_code_fences_stripped(self):
        raw = '```json\n{"action": "finish", "reasoning": "done"}\n```'
        thought = self.executor._parse_thought(raw, current_step=0, total_steps=1)
        assert thought.action == "finish"

    def test_next_step_capped_at_total(self):
        raw = json.dumps({
            "action": "call_tool",
            "reasoning": "last step",
            "tool_name": "x",
            "tool_args": {},
        })
        thought = self.executor._parse_thought(raw, current_step=4, total_steps=5)
        assert thought.next_step == 5  # min(4+1, 5)


# ---------------------------------------------------------------------------
# Tests: agent_loop
# ---------------------------------------------------------------------------

class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_immediate_finish(self):
        """LLM immediately returns finish → yields thought + completed."""
        reg = ToolRegistry()
        executor = Executor(api_key="test", tool_registry=reg)

        plan = _make_plan()

        finish_thought = Thought(
            action="finish",
            reasoning="Nothing to do",
            tool_call=None,
            next_step=0,
            message=Message(role="assistant", content="done"),
        )

        with patch.object(executor, "_think", new_callable=AsyncMock, return_value=finish_thought):
            events = []
            async for event in executor.agent_loop(plan, {}, max_turns=10):
                events.append(event)

        types = [e.type for e in events]
        assert "thought" in types
        assert "completed" in types

    @pytest.mark.asyncio
    async def test_one_tool_then_finish(self):
        """LLM calls one tool, then finishes."""
        reg = ToolRegistry()
        reg.register(SuccessTool("save_job"))
        executor = Executor(api_key="test", tool_registry=reg)

        plan = _make_plan("save_job")

        call_thought = Thought(
            action="call_tool",
            reasoning="Saving job",
            tool_call=ToolCall(tool_name="save_job", arguments={}),
            next_step=1,
            message=Message(role="assistant", content="saving"),
        )
        finish_thought = Thought(
            action="finish",
            reasoning="Done",
            tool_call=None,
            next_step=1,
            message=Message(role="assistant", content="done"),
        )

        think_mock = AsyncMock(side_effect=[call_thought, finish_thought])

        with patch.object(executor, "_think", think_mock):
            events = []
            async for event in executor.agent_loop(plan, {}, max_turns=10):
                events.append(event)

        types = [e.type for e in events]
        assert types == ["thought", "tool_start", "tool_result", "thought", "completed"]

    @pytest.mark.asyncio
    async def test_max_turns_reached(self):
        """Loop hits max_turns and yields max_turns_reached."""
        reg = ToolRegistry()
        reg.register(SuccessTool("loop_tool"))
        executor = Executor(api_key="test", tool_registry=reg)

        plan = _make_plan("loop_tool")

        # Always return call_tool to force hitting max_turns
        call_thought = Thought(
            action="call_tool",
            reasoning="Again",
            tool_call=ToolCall(tool_name="loop_tool", arguments={}),
            next_step=0,
            message=Message(role="assistant", content="again"),
        )

        with patch.object(executor, "_think", new_callable=AsyncMock, return_value=call_thought):
            events = []
            async for event in executor.agent_loop(plan, {}, max_turns=2):
                events.append(event)

        types = [e.type for e in events]
        assert "max_turns_reached" in types

    @pytest.mark.asyncio
    async def test_tool_failure_recorded_in_state(self):
        """Failed tool result errors are accumulated in state."""
        reg = ToolRegistry()
        reg.register(FailTool("bad_tool", fail_count=10))
        executor = Executor(api_key="test", tool_registry=reg)

        plan = _make_plan("bad_tool")

        call_thought = Thought(
            action="call_tool",
            reasoning="Try bad tool",
            tool_call=ToolCall(tool_name="bad_tool", arguments={}),
            next_step=1,
            message=Message(role="assistant", content="trying"),
        )
        finish_thought = Thought(
            action="finish",
            reasoning="Done",
            tool_call=None,
            next_step=1,
            message=Message(role="assistant", content="done"),
        )

        think_mock = AsyncMock(side_effect=[call_thought, finish_thought])

        with patch.object(executor, "_think", think_mock):
            events = []
            async for event in executor.agent_loop(plan, {}, max_turns=10):
                events.append(event)

        # Should have a tool_result event with success=False
        tool_results = [e for e in events if e.type == "tool_result"]
        assert len(tool_results) == 1
        assert tool_results[0].data["success"] is False
