"""state 模块单元测试"""

import json
from datetime import datetime

import pytest

from agent.state import (
    AgentEvent,
    AgentState,
    ErrorRecord,
    ExecutionPlan,
    Message,
    PlanStep,
    ToolCall,
    ToolResult,
)

# --- Helpers ---

def _make_error_record(**overrides) -> ErrorRecord:
    defaults = dict(
        timestamp=datetime(2025, 1, 15, 10, 30, 0),
        step_index=0,
        tool_name="search_jobs",
        error_type="timeout",
        error_message="request timed out",
        retry_count=2,
        resolved=False,
    )
    defaults.update(overrides)
    return ErrorRecord(**defaults)


def _make_plan_step(**overrides) -> PlanStep:
    defaults = dict(
        description="搜索岗位",
        tool_name="search_jobs",
        tool_args={"keyword": "AI", "city": "上海"},
        depends_on=[],
    )
    defaults.update(overrides)
    return PlanStep(**defaults)


def _make_plan(**overrides) -> ExecutionPlan:
    defaults = dict(
        steps=(
            _make_plan_step(),
            _make_plan_step(description="解析 JD", tool_name="parse_jd", depends_on=[0]),
        ),
        original_input="帮我搜索上海 AI 岗位",
        created_at=datetime(2025, 1, 15, 10, 0, 0),
    )
    defaults.update(overrides)
    return ExecutionPlan(**defaults)


# --- Message ---

class TestMessage:
    def test_creation(self):
        m = Message(role="user", content="hello")
        assert m.role == "user"
        assert m.content == "hello"

    def test_frozen(self):
        m = Message(role="user", content="hello")
        with pytest.raises(AttributeError):
            m.role = "assistant"  # type: ignore[misc]

    def test_roundtrip(self):
        m = Message(role="assistant", content="你好")
        assert Message.from_dict(m.to_dict()) == m


# --- ErrorRecord ---

class TestErrorRecord:
    def test_creation(self):
        e = _make_error_record()
        assert e.tool_name == "search_jobs"
        assert e.resolved is False

    def test_frozen(self):
        e = _make_error_record()
        with pytest.raises(AttributeError):
            e.resolved = True  # type: ignore[misc]

    def test_roundtrip(self):
        e = _make_error_record()
        assert ErrorRecord.from_dict(e.to_dict()) == e


# --- PlanStep ---

class TestPlanStep:
    def test_creation(self):
        s = _make_plan_step()
        assert s.tool_name == "search_jobs"
        assert s.depends_on == []

    def test_roundtrip(self):
        s = _make_plan_step(depends_on=[0, 1])
        assert PlanStep.from_dict(s.to_dict()) == s


# --- ExecutionPlan ---

class TestExecutionPlan:
    def test_creation(self):
        p = _make_plan()
        assert len(p.steps) == 2
        assert p.original_input == "帮我搜索上海 AI 岗位"

    def test_roundtrip(self):
        p = _make_plan()
        assert ExecutionPlan.from_dict(p.to_dict()) == p


# --- ToolCall ---

class TestToolCall:
    def test_creation(self):
        tc = ToolCall(tool_name="search_jobs", arguments={"keyword": "AI"})
        assert tc.tool_name == "search_jobs"

    def test_roundtrip(self):
        tc = ToolCall(tool_name="search_jobs", arguments={"keyword": "AI", "city": "上海"})
        assert ToolCall.from_dict(tc.to_dict()) == tc


# --- ToolResult ---

class TestToolResult:
    def test_creation(self):
        tr = ToolResult(
            success=True,
            data={"jobs": [1, 2, 3]},
            message=Message(role="tool", content="found 3 jobs"),
            errors=(),
        )
        assert tr.success is True
        assert len(tr.errors) == 0

    def test_roundtrip(self):
        tr = ToolResult(
            success=False,
            data={},
            message=Message(role="tool", content="error"),
            errors=(_make_error_record(),),
        )
        assert ToolResult.from_dict(tr.to_dict()) == tr


# --- AgentEvent ---

class TestAgentEvent:
    def test_thought_factory(self):
        e = AgentEvent.thought("需要先搜索岗位")
        assert e.type == "thought"
        assert e.data["content"] == "需要先搜索岗位"

    def test_tool_start_factory(self):
        tc = ToolCall(tool_name="search_jobs", arguments={"keyword": "AI"})
        e = AgentEvent.tool_start(tc)
        assert e.type == "tool_start"
        assert e.data["tool_name"] == "search_jobs"

    def test_tool_result_factory(self):
        tr = ToolResult(
            success=True, data={"count": 5},
            message=Message(role="tool", content="ok"), errors=(),
        )
        e = AgentEvent.tool_result(tr)
        assert e.type == "tool_result"
        assert e.data["success"] is True

    def test_error_factory(self):
        e = AgentEvent.error("something broke", step_index=2)
        assert e.type == "error"
        assert e.data["step_index"] == 2

    def test_roundtrip(self):
        e = AgentEvent.thought("thinking")
        assert AgentEvent.from_dict(e.to_dict()) == e


# --- AgentState ---

class TestAgentState:
    def test_initial_from_plan(self):
        plan = _make_plan()
        state = AgentState.initial(plan)
        assert state.turn_count == 0
        assert state.current_step == 0
        assert len(state.messages) == 1
        assert state.messages[0].role == "user"
        assert state.messages[0].content == plan.original_input
        assert state.errors == ()
        assert state.intermediate_results == {}

    def test_frozen(self):
        state = AgentState.initial(_make_plan())
        with pytest.raises(AttributeError):
            state.turn_count = 5  # type: ignore[misc]

    def test_roundtrip(self):
        state = AgentState(
            messages=(
                Message(role="user", content="hello"),
                Message(role="assistant", content="hi"),
            ),
            current_step=1,
            intermediate_results={"key": "value", "nested": {"a": 1}},
            errors=(_make_error_record(),),
            turn_count=3,
        )
        restored = AgentState.from_dict(state.to_dict())
        assert restored == state

    def test_serialization_is_json_compatible(self):
        state = AgentState.initial(_make_plan())
        # Should be JSON-serializable
        json_str = json.dumps(state.to_dict(), ensure_ascii=False)
        data = json.loads(json_str)
        restored = AgentState.from_dict(data)
        assert restored == state
