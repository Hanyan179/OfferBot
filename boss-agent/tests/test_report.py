"""
执行报告生成模块单元测试
"""

from __future__ import annotations

from datetime import datetime

from agent.report import StepReport, generate_report
from agent.state import AgentEvent, ExecutionPlan, PlanStep, ToolCall


def _make_plan(*tool_names: str) -> ExecutionPlan:
    steps = tuple(
        PlanStep(description=f"Step {i}: {n}", tool_name=n, tool_args={}, depends_on=[])
        for i, n in enumerate(tool_names)
    )
    return ExecutionPlan(steps=steps, original_input="test", created_at=datetime.now())


class TestGenerateReport:
    def test_all_steps_success(self):
        plan = _make_plan("save_job", "get_stats")
        events = [
            AgentEvent.tool_start(ToolCall(tool_name="save_job", arguments={})),
            AgentEvent.tool_result(
                _make_tool_result(True, {"save_job": {"job_id": 1, "_elapsed_seconds": 0.5}})
            ),
            AgentEvent.tool_start(ToolCall(tool_name="get_stats", arguments={})),
            AgentEvent.tool_result(
                _make_tool_result(True, {"get_stats": {"total": 10, "_elapsed_seconds": 0.3}})
            ),
        ]

        report = generate_report(plan, events)

        assert report.total_steps == 2
        assert report.completed_steps == 2
        assert report.failed_steps == 0
        assert report.skipped_steps == 0
        assert len(report.step_reports) == 2
        assert report.step_reports[0].status == "success"
        assert report.step_reports[1].status == "success"

    def test_partial_completion(self):
        plan = _make_plan("save_job", "parse_jd", "get_stats")
        events = [
            AgentEvent.tool_start(ToolCall(tool_name="save_job", arguments={})),
            AgentEvent.tool_result(
                _make_tool_result(True, {"save_job": {"_elapsed_seconds": 0.1}})
            ),
            AgentEvent.tool_start(ToolCall(tool_name="parse_jd", arguments={})),
            AgentEvent.tool_result(
                _make_tool_result(False, {})
            ),
            # get_stats was never executed (skipped)
        ]

        report = generate_report(plan, events)

        assert report.total_steps == 3
        assert report.completed_steps == 1
        assert report.failed_steps == 1
        assert report.skipped_steps == 1
        assert report.step_reports[0].status == "success"
        assert report.step_reports[1].status == "failed"
        assert report.step_reports[2].status == "skipped"

    def test_empty_plan(self):
        plan = ExecutionPlan(steps=(), original_input="empty", created_at=datetime.now())
        report = generate_report(plan, [])

        assert report.total_steps == 0
        assert report.completed_steps == 0
        assert report.step_reports == []

    def test_to_dict(self):
        plan = _make_plan("save_job")
        events = [
            AgentEvent.tool_start(ToolCall(tool_name="save_job", arguments={})),
            AgentEvent.tool_result(
                _make_tool_result(True, {"save_job": {"_elapsed_seconds": 0.2}})
            ),
        ]
        report = generate_report(plan, events)
        d = report.to_dict()

        assert d["total_steps"] == 1
        assert d["completed_steps"] == 1
        assert len(d["step_reports"]) == 1
        assert "created_at" in d

    def test_to_markdown(self):
        plan = _make_plan("save_job", "get_stats")
        events = [
            AgentEvent.tool_start(ToolCall(tool_name="save_job", arguments={})),
            AgentEvent.tool_result(
                _make_tool_result(True, {"save_job": {"_elapsed_seconds": 0.5}})
            ),
            AgentEvent.tool_start(ToolCall(tool_name="get_stats", arguments={})),
            AgentEvent.tool_result(
                _make_tool_result(False, {})
            ),
        ]
        report = generate_report(plan, events)
        md = report.to_markdown()

        assert "执行报告" in md
        assert "✅" in md
        assert "❌" in md
        assert "save_job" in md


class TestStepReport:
    def test_to_dict(self):
        sr = StepReport(
            step_index=0,
            description="test step",
            tool_name="save_job",
            status="success",
            elapsed_seconds=1.5,
            summary="saved 1 job",
        )
        d = sr.to_dict()
        assert d["step_index"] == 0
        assert d["status"] == "success"
        assert d["elapsed_seconds"] == 1.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_result(success: bool, data: dict):
    from agent.state import Message, ToolResult
    return ToolResult(
        success=success,
        data=data,
        message=Message(role="tool", content="result"),
        errors=(),
    )
