"""
核心数据结构和类型定义

定义 Agent 核心引擎使用的所有 dataclass：
AgentState（不可变状态）、ExecutionPlan、PlanStep、
AgentEvent、ToolCall、ToolResult、ErrorRecord、Message。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Message:
    """对话消息"""
    role: str  # "user" | "assistant" | "tool"
    content: str

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Message":
        return Message(role=data["role"], content=data["content"])


@dataclass(frozen=True)
class ErrorRecord:
    """错误记录"""
    timestamp: datetime
    step_index: int
    tool_name: str
    error_type: str       # "timeout" | "api_error" | "parse_error" | "auth_error" | ...
    error_message: str
    retry_count: int
    resolved: bool        # 是否通过重试解决

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "step_index": self.step_index,
            "tool_name": self.tool_name,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "resolved": self.resolved,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ErrorRecord":
        return ErrorRecord(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            step_index=data["step_index"],
            tool_name=data["tool_name"],
            error_type=data["error_type"],
            error_message=data["error_message"],
            retry_count=data["retry_count"],
            resolved=data["resolved"],
        )


@dataclass(frozen=True)
class PlanStep:
    """执行计划中的单个步骤"""
    description: str
    tool_name: str
    tool_args: dict[str, Any]
    depends_on: list[int]  # 依赖的步骤索引

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "depends_on": self.depends_on,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PlanStep":
        return PlanStep(
            description=data["description"],
            tool_name=data["tool_name"],
            tool_args=dict(data["tool_args"]),
            depends_on=list(data["depends_on"]),
        )


@dataclass(frozen=True)
class ExecutionPlan:
    """执行计划"""
    steps: tuple[PlanStep, ...]
    original_input: str
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "original_input": self.original_input,
            "created_at": self.created_at.isoformat(),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ExecutionPlan":
        return ExecutionPlan(
            steps=tuple(PlanStep.from_dict(s) for s in data["steps"]),
            original_input=data["original_input"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )


@dataclass(frozen=True)
class ToolCall:
    """Tool 调用请求"""
    tool_name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"tool_name": self.tool_name, "arguments": self.arguments}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ToolCall":
        return ToolCall(
            tool_name=data["tool_name"],
            arguments=dict(data["arguments"]),
        )


@dataclass(frozen=True)
class ToolResult:
    """Tool 执行结果"""
    success: bool
    data: dict[str, Any]
    message: Message
    errors: tuple[ErrorRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "message": self.message.to_dict(),
            "errors": [e.to_dict() for e in self.errors],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ToolResult":
        return ToolResult(
            success=data["success"],
            data=dict(data["data"]),
            message=Message.from_dict(data["message"]),
            errors=tuple(ErrorRecord.from_dict(e) for e in data["errors"]),
        )


@dataclass(frozen=True)
class AgentEvent:
    """Agent 事件，yield 给 UI 层实时展示"""
    type: str  # "thought" | "tool_start" | "tool_result" | "completed" | "error" | "max_turns_reached" | "action_card"
    data: dict[str, Any]
    timestamp: datetime

    # --- Factory methods ---

    @staticmethod
    def thought(content: str) -> "AgentEvent":
        return AgentEvent(
            type="thought",
            data={"content": content},
            timestamp=datetime.now(),
        )

    @staticmethod
    def tool_start(tool_call: ToolCall) -> "AgentEvent":
        return AgentEvent(
            type="tool_start",
            data={"tool_name": tool_call.tool_name, "arguments": tool_call.arguments},
            timestamp=datetime.now(),
        )

    @staticmethod
    def tool_result(result: ToolResult) -> "AgentEvent":
        return AgentEvent(
            type="tool_result",
            data={"success": result.success, "data": result.data},
            timestamp=datetime.now(),
        )

    @staticmethod
    def completed(state: "AgentState") -> "AgentEvent":
        return AgentEvent(
            type="completed",
            data={"turn_count": state.turn_count, "current_step": state.current_step},
            timestamp=datetime.now(),
        )

    @staticmethod
    def error(message: str, step_index: int = -1) -> "AgentEvent":
        return AgentEvent(
            type="error",
            data={"message": message, "step_index": step_index},
            timestamp=datetime.now(),
        )

    @staticmethod
    def max_turns_reached(state: "AgentState") -> "AgentEvent":
        return AgentEvent(
            type="max_turns_reached",
            data={"turn_count": state.turn_count, "current_step": state.current_step},
            timestamp=datetime.now(),
        )

    @staticmethod
    def action_card(card_data: dict[str, Any]) -> "AgentEvent":
        return AgentEvent(
            type="action_card",
            data=card_data,
            timestamp=datetime.now(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AgentEvent":
        return AgentEvent(
            type=data["type"],
            data=dict(data["data"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


@dataclass(frozen=True)
class AgentState:
    """
    不可变状态对象，每次循环整体替换。

    参考 Claude Code 的不可变状态模式：
    状态更新通过创建新实例实现，而非修改现有字段。
    """
    messages: tuple[Message, ...]
    current_step: int
    intermediate_results: dict[str, Any]
    errors: tuple[ErrorRecord, ...]
    turn_count: int

    @staticmethod
    def initial(plan: ExecutionPlan) -> "AgentState":
        """从执行计划创建初始状态"""
        return AgentState(
            messages=(Message(role="user", content=plan.original_input),),
            current_step=0,
            intermediate_results={},
            errors=(),
            turn_count=0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": [m.to_dict() for m in self.messages],
            "current_step": self.current_step,
            "intermediate_results": self.intermediate_results,
            "errors": [e.to_dict() for e in self.errors],
            "turn_count": self.turn_count,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AgentState":
        return AgentState(
            messages=tuple(Message.from_dict(m) for m in data["messages"]),
            current_step=data["current_step"],
            intermediate_results=dict(data["intermediate_results"]),
            errors=tuple(ErrorRecord.from_dict(e) for e in data["errors"]),
            turn_count=data["turn_count"],
        )
