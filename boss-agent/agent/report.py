"""
执行报告生成

任务完成后输出结构化执行报告：每个步骤的执行状态、耗时、结果摘要。
支持部分完成场景（某些步骤跳过或失败）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent.state import AgentEvent, AgentState, ExecutionPlan


@dataclass
class StepReport:
    """单个步骤的执行报告。"""
    step_index: int
    description: str
    tool_name: str
    status: str  # "success" | "failed" | "skipped"
    elapsed_seconds: float
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "description": self.description,
            "tool_name": self.tool_name,
            "status": self.status,
            "elapsed_seconds": self.elapsed_seconds,
            "summary": self.summary,
        }


@dataclass
class ExecutionReport:
    """完整的执行报告。"""
    plan_input: str
    total_steps: int
    completed_steps: int
    failed_steps: int
    skipped_steps: int
    total_elapsed_seconds: float
    step_reports: list[StepReport]
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_input": self.plan_input,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "skipped_steps": self.skipped_steps,
            "total_elapsed_seconds": self.total_elapsed_seconds,
            "step_reports": [s.to_dict() for s in self.step_reports],
            "created_at": self.created_at.isoformat(),
        }

    def to_markdown(self) -> str:
        """格式化为可读的 Markdown 文本。"""
        lines = [
            f"## 执行报告",
            f"",
            f"**原始指令**: {self.plan_input}",
            f"**总步骤数**: {self.total_steps}",
            f"**完成**: {self.completed_steps} | **失败**: {self.failed_steps} | **跳过**: {self.skipped_steps}",
            f"**总耗时**: {self.total_elapsed_seconds:.2f}s",
            f"",
        ]
        for sr in self.step_reports:
            icon = {"success": "✅", "failed": "❌", "skipped": "⏭️"}.get(sr.status, "❓")
            lines.append(f"{icon} **步骤 {sr.step_index}** [{sr.tool_name}] — {sr.description}")
            lines.append(f"   状态: {sr.status} | 耗时: {sr.elapsed_seconds:.2f}s")
            lines.append(f"   {sr.summary}")
            lines.append("")
        return "\n".join(lines)


def generate_report(
    plan: ExecutionPlan,
    events: list[AgentEvent],
) -> ExecutionReport:
    """
    从执行计划和事件流生成执行报告。

    Args:
        plan: 原始执行计划
        events: agent_loop yield 出的所有 AgentEvent 列表

    Returns:
        ExecutionReport
    """
    total_steps = len(plan.steps)

    # Track per-step results from events
    step_results: dict[int, dict[str, Any]] = {}
    current_tool: str | None = None
    current_step_idx = 0

    for event in events:
        if event.type == "tool_start":
            current_tool = event.data.get("tool_name", "")
        elif event.type == "tool_result":
            success = event.data.get("success", False)
            data = event.data.get("data", {})

            # Extract elapsed time from tool result data
            elapsed = 0.0
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, dict) and "_elapsed_seconds" in v:
                        elapsed = v["_elapsed_seconds"]
                        break

            # Summarize result
            summary = _summarize_result(data, success)

            step_results[current_step_idx] = {
                "tool_name": current_tool or "",
                "success": success,
                "elapsed": elapsed,
                "summary": summary,
            }
            current_step_idx += 1

    # Build step reports
    step_reports: list[StepReport] = []
    total_elapsed = 0.0

    for i, step in enumerate(plan.steps):
        if i in step_results:
            r = step_results[i]
            status = "success" if r["success"] else "failed"
            elapsed = r["elapsed"]
            summary = r["summary"]
        else:
            status = "skipped"
            elapsed = 0.0
            summary = "步骤未执行"

        total_elapsed += elapsed
        step_reports.append(StepReport(
            step_index=i,
            description=step.description,
            tool_name=step.tool_name,
            status=status,
            elapsed_seconds=elapsed,
            summary=summary,
        ))

    completed = sum(1 for s in step_reports if s.status == "success")
    failed = sum(1 for s in step_reports if s.status == "failed")
    skipped = sum(1 for s in step_reports if s.status == "skipped")

    return ExecutionReport(
        plan_input=plan.original_input,
        total_steps=total_steps,
        completed_steps=completed,
        failed_steps=failed,
        skipped_steps=skipped,
        total_elapsed_seconds=round(total_elapsed, 3),
        step_reports=step_reports,
        created_at=datetime.now(),
    )


def _summarize_result(data: Any, success: bool) -> str:
    """生成结果摘要文本。"""
    if not success:
        return "执行失败"

    if isinstance(data, dict):
        # Try to extract meaningful summary from result data
        parts: list[str] = []
        for key, val in data.items():
            if isinstance(val, dict):
                # Remove internal fields
                clean = {k: v for k, v in val.items() if not k.startswith("_")}
                if clean:
                    parts.append(f"{key}: {_compact_repr(clean)}")
            else:
                parts.append(f"{key}: {val}")
        return "; ".join(parts) if parts else "执行成功"

    return str(data)[:200] if data else "执行成功"


def _compact_repr(d: dict, max_len: int = 150) -> str:
    """Compact dict representation, truncated."""
    import json
    s = json.dumps(d, ensure_ascii=False, default=str)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s
