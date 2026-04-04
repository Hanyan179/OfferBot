"""
Planner — 意图理解与任务拆解

将用户自然语言指令解析为 ExecutionPlan（包含有序 PlanStep 列表）。
支持 replan：根据执行中间状态和错误信息重新规划。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from agent.llm_client import LLMClient
from agent.state import AgentState, ExecutionPlan, PlanStep
from agent.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt for the Planner LLM call
# ---------------------------------------------------------------------------

_PLAN_SYSTEM_PROMPT = """\
你是一个求职 Agent 的任务规划器。你的职责是将用户的自然语言指令拆解为一系列有序的执行步骤。

每个步骤必须调用一个已注册的 Tool。可用的 Tool 列表会在消息中提供。

请以 JSON 格式输出执行计划，格式如下：
{
  "steps": [
    {
      "description": "步骤描述",
      "tool_name": "tool 名称（必须是可用 Tool 之一）",
      "tool_args": {"参数名": "参数值"},
      "depends_on": []
    }
  ]
}

规则：
1. tool_name 必须是可用 Tool 列表中的名称之一
2. depends_on 是该步骤依赖的前置步骤索引列表（从 0 开始）
3. 如果用户意图不明确，生成一个步骤用于澄清
4. 步骤应尽量精简，避免冗余
5. 只输出 JSON，不要输出其他内容
"""

_REPLAN_SYSTEM_PROMPT = """\
你是一个求职 Agent 的任务规划器。当前任务执行遇到问题，需要你根据已有状态重新规划。

已完成的步骤和错误信息会在消息中提供。请生成新的执行计划，跳过已成功完成的步骤。

输出格式同上：JSON 格式的 steps 列表。只输出 JSON，不要输出其他内容。
"""


class Planner:
    """意图理解与任务拆解，将自然语言指令转为 ExecutionPlan。"""

    def __init__(
        self,
        api_key: str = "",
        model: str = "qwen-plus",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        tool_registry: ToolRegistry | None = None,
        llm_client: LLMClient | None = None,
    ):
        self._registry = tool_registry
        # 允许外部注入 LLMClient（方便测试），否则自动创建
        self._llm = llm_client or LLMClient(api_key=api_key, model=model, base_url=base_url)

    @property
    def tool_registry(self) -> ToolRegistry | None:
        return self._registry

    @tool_registry.setter
    def tool_registry(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def plan(self, user_input: str, context: dict[str, Any] | None = None) -> ExecutionPlan:
        """
        调用 DashScope LLM 解析用户意图，生成有序执行步骤列表。

        Args:
            user_input: 用户自然语言指令
            context: 可选上下文（用户偏好、历史等）

        Returns:
            ExecutionPlan 包含有序 PlanStep 列表
        """
        available_tools = self._get_available_tools_description()

        user_message = f"用户指令: {user_input}\n\n可用 Tool 列表:\n{available_tools}"
        if context:
            user_message += f"\n\n上下文信息:\n{json.dumps(context, ensure_ascii=False, indent=2)}"

        messages = [
            {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        raw_response = await self._call_llm(messages)
        steps = self._parse_plan_response(raw_response)
        steps = self._validate_steps(steps)

        return ExecutionPlan(
            steps=tuple(steps),
            original_input=user_input,
            created_at=datetime.now(),
        )

    async def replan(self, state: AgentState, error: str) -> ExecutionPlan:
        """
        根据执行中间状态和错误信息重新规划。

        Args:
            state: 当前 AgentState
            error: 错误描述

        Returns:
            新的 ExecutionPlan
        """
        available_tools = self._get_available_tools_description()

        state_summary = (
            f"已执行到步骤 {state.current_step}，共 {state.turn_count} 轮。\n"
            f"中间结果: {json.dumps(state.intermediate_results, ensure_ascii=False, default=str)}\n"
            f"错误记录: {json.dumps([e.to_dict() for e in state.errors], ensure_ascii=False)}\n"
            f"当前错误: {error}"
        )

        original_input = ""
        for msg in state.messages:
            if msg.role == "user":
                original_input = msg.content
                break

        user_message = (
            f"原始用户指令: {original_input}\n\n"
            f"当前执行状态:\n{state_summary}\n\n"
            f"可用 Tool 列表:\n{available_tools}\n\n"
            f"请重新规划剩余步骤。"
        )

        messages = [
            {"role": "system", "content": _REPLAN_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        raw_response = await self._call_llm(messages)
        steps = self._parse_plan_response(raw_response)
        steps = self._validate_steps(steps)

        return ExecutionPlan(
            steps=tuple(steps),
            original_input=original_input,
            created_at=datetime.now(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_available_tools_description(self) -> str:
        """构建可用 Tool 的文本描述供 LLM 参考。"""
        if self._registry is None or self._registry.tool_count == 0:
            return "(无可用 Tool)"

        lines: list[str] = []
        for schema in self._registry.get_all_schemas():
            func = schema["function"]
            params_desc = json.dumps(func["parameters"], ensure_ascii=False)
            lines.append(f"- {func['name']}: {func['description']}\n  参数: {params_desc}")
        return "\n".join(lines)

    async def _call_llm(self, messages: list[dict]) -> str:
        """通过 LLMClient 调用 LLM（OpenAI 兼容格式）。"""
        return await self._llm.chat(messages)

    def _parse_plan_response(self, raw: str) -> list[PlanStep]:
        """从 LLM 响应中解析 PlanStep 列表。"""
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (fences)
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON: %s", text[:200])
            return []

        steps: list[PlanStep] = []
        raw_steps = data.get("steps", [])
        for s in raw_steps:
            steps.append(PlanStep(
                description=s.get("description", ""),
                tool_name=s.get("tool_name", ""),
                tool_args=dict(s.get("tool_args", {})),
                depends_on=list(s.get("depends_on", [])),
            ))
        return steps

    def _validate_steps(self, steps: list[PlanStep]) -> list[PlanStep]:
        """
        校验步骤：确保每个 PlanStep 的 tool_name 在 ToolRegistry 中已注册。
        未注册的 tool 会被过滤掉并记录警告。
        """
        if self._registry is None:
            return steps

        valid: list[PlanStep] = []
        registered_names = set(self._registry.list_tool_names())

        for step in steps:
            if step.tool_name in registered_names:
                valid.append(step)
            else:
                logger.warning(
                    "Planner: tool_name '%s' not in registry, skipping step: %s",
                    step.tool_name,
                    step.description,
                )
        return valid
