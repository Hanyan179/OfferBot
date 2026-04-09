"""
Executor — ReAct Agent Loop 执行器

系统的心脏：while True 循环，Thought → Action → Observation。
参考 Claude Code 的 queryLoop() 设计。

yield AgentEvent 给 UI 层实时展示执行过程。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncGenerator

from agent.llm_client import LLMClient
from agent.state import (
    AgentEvent,
    AgentState,
    ErrorRecord,
    ExecutionPlan,
    Message,
    ToolCall,
    ToolResult,
)
from agent.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thought — LLM 决策结果
# ---------------------------------------------------------------------------

@dataclass
class Thought:
    """LLM 的一次思考结果。"""
    action: str  # "call_tool" | "finish"
    reasoning: str
    tool_call: ToolCall | None  # action == "call_tool" 时非 None
    next_step: int
    message: Message  # 记录到 state.messages


# ---------------------------------------------------------------------------
# System prompt for the Executor LLM call
# ---------------------------------------------------------------------------

_THINK_SYSTEM_PROMPT = """\
你是一个求职 Agent 的执行器。你正在逐步执行一个任务计划。

当前执行计划和状态会在消息中提供。你需要决定下一步动作。

请以 JSON 格式输出决策：
{
  "action": "call_tool" 或 "finish",
  "reasoning": "你的思考过程",
  "tool_name": "要调用的 tool 名称（action=call_tool 时必填）",
  "tool_args": {"参数": "值"}（action=call_tool 时必填）
}

规则：
1. 根据计划中的步骤顺序执行
2. 如果所有步骤已完成，action 设为 "finish"
3. 根据前序步骤的结果调整后续步骤的参数
4. 只输出 JSON，不要输出其他内容
"""


class Executor:
    """ReAct Agent Loop 执行器 — 系统的心脏。"""

    def __init__(
        self,
        api_key: str = "",
        model: str = "qwen-plus",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        tool_registry: ToolRegistry | None = None,
        llm_client: LLMClient | None = None,
    ):
        self._registry = tool_registry
        self._llm = llm_client or LLMClient(api_key=api_key, model=model, base_url=base_url)

    @property
    def tool_registry(self) -> ToolRegistry | None:
        return self._registry

    @tool_registry.setter
    def tool_registry(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def chat(
        self,
        messages: list[dict],
        context: dict[str, Any] | None = None,
        max_turns: int = 10,
        system_prompt: str | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        对话模式 Agent Loop — 参考 Claude Code 的 queryLoop()。

        不需要预先的 ExecutionPlan。LLM 直接基于对话历史 + 可用工具
        自行决定是回复文本、调用工具、还是两者同时。

        Args:
            messages: OpenAI 格式的对话历史
            context: Agent 上下文（db 等资源）
            max_turns: 最大工具调用轮数（防止无限循环）
            system_prompt: 自定义 system prompt（为 None 时使用默认）

        Yields:
            AgentEvent 给 UI 层实时展示
        """
        if system_prompt is None:
            from agent.system_prompt import SYSTEM_PROMPT
            system_prompt = SYSTEM_PROMPT

        # 初始化 context 和 active_toolsets
        if context is None:
            context = {}
        if "active_toolsets" not in context:
            context["active_toolsets"] = {"core"}
        # 注入 registry 引用（供 activate_toolset 使用）
        if self._registry and "registry" not in context:
            context["registry"] = self._registry

        # 构建完整消息列表（system prompt + 对话历史）
        full_messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        turn = 0
        while turn < max_turns:
            # 每轮重新获取工具 Schema（activate_toolset 可能已修改 active_toolsets）
            tools = (
                self._registry.get_schemas_for_toolsets(context["active_toolsets"])
                if self._registry
                else []
            )

            # 调用 LLM（带 function calling）
            try:
                response = await self._llm.chat_with_tools(
                    messages=full_messages,
                    tools=tools if tools else None,
                )
            except Exception as e:
                logger.error("LLM call error: %s", e)
                yield AgentEvent.error(f"LLM 调用失败: {e}")
                return

            # 提取文本回复和思考内容
            text_content = response.content or ""
            tool_calls = response.tool_calls or []

            # 提取思考内容（千问 Qwen3 系列的 reasoning_content）
            reasoning = getattr(response, "reasoning_content", None) or ""
            if reasoning:
                yield AgentEvent(
                    type="thinking",
                    data={"content": reasoning},
                    timestamp=datetime.now(),
                )

            # 如果有文本回复，yield 给 UI
            if text_content:
                yield AgentEvent(
                    type="assistant_message",
                    data={"content": text_content},
                    timestamp=datetime.now(),
                )

            # 如果没有工具调用，对话结束
            if not tool_calls:
                return

            # 把 assistant 消息（含 tool_calls）加入历史
            # 使用 to_dict() 保留 Gemini 的 thought_signature（缺失会导致 400 错误）
            full_messages.append(response.to_dict())

            # 执行每个工具调用
            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                call = ToolCall(tool_name=tool_name, arguments=tool_args)
                yield AgentEvent.tool_start(call)

                result = await self._execute_tool(call, context or {}, max_retries=3)
                yield AgentEvent.tool_result(result)

                # 检查是否为 action_card（需要用户确认的操作）
                result_content = result.message.content if result.message else ""
                is_action_card = False
                is_ui_render = False
                try:
                    result_parsed = json.loads(result_content)
                    if isinstance(result_parsed, dict):
                        # Tool 返回值驱动：自动激活 toolset
                        toolsets_to_activate = result_parsed.pop("_activate_toolsets", None)
                        if toolsets_to_activate and isinstance(toolsets_to_activate, list):
                            for ts in toolsets_to_activate:
                                context["active_toolsets"].add(ts)

                        if result_parsed.get("action") == "confirm_required":
                            yield AgentEvent.action_card(result_parsed)
                            is_action_card = True
                            # action_card 是异步任务，不需要 AI 等待
                            # 直接告诉 LLM 任务已提交，立即结束本轮 loop
                            card_type = result_parsed.get("card_type", "unknown")
                            yield AgentEvent(
                                type="assistant_message",
                                data={"content": f"已为你生成操作卡片，请在上方确认参数后点击执行。任务启动后可以在右侧面板查看进度，我们可以继续聊其他的 😊"},
                                timestamp=datetime.now(),
                            )
                            return  # 立即结束 loop，不让 LLM 继续轮询
                        elif "for_ui" in result_parsed and "for_agent" in result_parsed:
                            # 结果分流：for_ui 推前端渲染，for_agent 给 LLM
                            yield AgentEvent.ui_render({
                                "tool_name": tool_name,
                                "for_ui": result_parsed["for_ui"],
                            })
                            is_ui_render = True
                            result_content = json.dumps(
                                result_parsed["for_agent"], ensure_ascii=False
                            )
                except (json.JSONDecodeError, TypeError):
                    pass

                if not is_action_card and not is_ui_render and len(result_content) > 2000:
                    # 尝试解析 JSON，提取关键字段做摘要
                    try:
                        import json as _json
                        data = _json.loads(result_content)
                        summary_parts = []
                        if isinstance(data, dict):
                            if "success" in data:
                                summary_parts.append(f"success={data['success']}")
                            if "error" in data and data["error"]:
                                summary_parts.append(f"error={data['error']}")
                            if "message" in data:
                                summary_parts.append(f"message={data['message']}")
                            # 数据类结果：只保留计数
                            if "data" in data and isinstance(data["data"], dict):
                                for k, v in data["data"].items():
                                    if isinstance(v, (int, float, str, bool)):
                                        summary_parts.append(f"{k}={v}")
                                    elif isinstance(v, list):
                                        summary_parts.append(f"{k}=[{len(v)} items]")
                        result_content = "{" + ", ".join(summary_parts) + "}"
                    except Exception:
                        result_content = result_content[:1500] + "...(truncated)"
                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_content,
                })

            turn += 1

        # 达到最大轮数
        yield AgentEvent(
            type="max_turns_reached",
            data={"turn_count": turn},
            timestamp=datetime.now(),
        )

    async def agent_loop(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any],
        max_turns: int = 50,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        核心循环，参考 Claude Code 的 queryLoop()。
        yield AgentEvent 给 UI 层实时展示。

        Args:
            plan: 执行计划
            context: Agent 上下文（包含 db 等资源）
            max_turns: 最大循环次数
        """
        state = AgentState.initial(plan)
        turn_count = 0

        while True:
            if turn_count >= max_turns:
                yield AgentEvent.max_turns_reached(state)
                return

            # Phase 1: Thought — LLM 决定下一步
            try:
                thought = await self._think(state, plan, context)
            except Exception as e:
                logger.error("Think phase error: %s", e)
                yield AgentEvent.error(f"思考阶段出错: {e}", state.current_step)
                return

            yield AgentEvent.thought(thought.reasoning)

            if thought.action == "finish":
                yield AgentEvent.completed(state)
                return

            # Phase 2: Action — 调用 Tool
            tool_call = thought.tool_call
            if tool_call is None:
                yield AgentEvent.error("思考结果缺少 tool_call", state.current_step)
                return

            yield AgentEvent.tool_start(tool_call)

            result = await self._execute_tool(tool_call, context, max_retries=3)
            yield AgentEvent.tool_result(result)

            # Phase 3: Observation — 更新状态（整体替换）
            new_errors = state.errors
            if not result.success:
                new_errors = (*state.errors, *result.errors)

            state = AgentState(
                messages=(*state.messages, thought.message, result.message),
                current_step=thought.next_step,
                intermediate_results={**state.intermediate_results, **result.data},
                errors=new_errors,
                turn_count=turn_count + 1,
            )
            turn_count += 1

    async def _think(
        self,
        state: AgentState,
        plan: ExecutionPlan,
        context: dict[str, Any],
    ) -> Thought:
        """调用 LLM，传入当前状态和可用 Tool 列表，获取决策。"""
        # Build context message for LLM
        plan_desc = "\n".join(
            f"  步骤 {i}: [{s.tool_name}] {s.description}"
            for i, s in enumerate(plan.steps)
        )

        available_tools = ""
        if self._registry:
            schemas = self._registry.get_all_schemas()
            available_tools = json.dumps(schemas, ensure_ascii=False, indent=2)

        intermediate = json.dumps(
            state.intermediate_results, ensure_ascii=False, default=str
        )
        errors_desc = json.dumps(
            [e.to_dict() for e in state.errors], ensure_ascii=False
        )

        user_content = (
            f"执行计划:\n{plan_desc}\n\n"
            f"当前步骤: {state.current_step} / {len(plan.steps)}\n"
            f"已执行轮数: {state.turn_count}\n"
            f"中间结果: {intermediate}\n"
            f"错误记录: {errors_desc}\n\n"
            f"可用 Tool:\n{available_tools}"
        )

        messages = [
            {"role": "system", "content": _THINK_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        raw = await self._call_llm(messages)
        return self._parse_thought(raw, state.current_step, len(plan.steps))

    async def _execute_tool(
        self,
        tool_call: ToolCall,
        context: dict[str, Any],
        max_retries: int = 3,
    ) -> ToolResult:
        """执行 Tool，带重试逻辑（最多 max_retries 次，指数退避）。"""
        if self._registry is None:
            return ToolResult(
                success=False,
                data={},
                message=Message(role="tool", content="ToolRegistry not available"),
                errors=(ErrorRecord(
                    timestamp=datetime.now(),
                    step_index=-1,
                    tool_name=tool_call.tool_name,
                    error_type="config_error",
                    error_message="ToolRegistry not configured",
                    retry_count=0,
                    resolved=False,
                ),),
            )

        tool = self._registry.get_tool(tool_call.tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                data={},
                message=Message(
                    role="tool",
                    content=f"Tool '{tool_call.tool_name}' not found in registry",
                ),
                errors=(ErrorRecord(
                    timestamp=datetime.now(),
                    step_index=-1,
                    tool_name=tool_call.tool_name,
                    error_type="not_found",
                    error_message=f"Tool '{tool_call.tool_name}' not registered",
                    retry_count=0,
                    resolved=False,
                ),),
            )

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                start_time = time.monotonic()
                result_data = await tool.execute(tool_call.arguments, context)
                elapsed = time.monotonic() - start_time

                # Normalize result_data to dict
                if not isinstance(result_data, dict):
                    result_data = {"result": result_data}

                result_data["_elapsed_seconds"] = round(elapsed, 3)

                return ToolResult(
                    success=True,
                    data={tool_call.tool_name: result_data},
                    message=Message(
                        role="tool",
                        content=json.dumps(result_data, ensure_ascii=False, default=str),
                    ),
                    errors=(),
                )

            except Exception as e:
                last_error = e
                logger.warning(
                    "Tool '%s' attempt %d/%d failed: %s",
                    tool_call.tool_name,
                    attempt + 1,
                    max_retries,
                    e,
                )
                if attempt < max_retries - 1:
                    delay = 2 ** (attempt + 1)  # 2s, 4s, 8s
                    await asyncio.sleep(delay)

        # All retries exhausted
        error_msg = str(last_error) if last_error else "Unknown error"
        return ToolResult(
            success=False,
            data={},
            message=Message(role="tool", content=f"Tool '{tool_call.tool_name}' failed: {error_msg}"),
            errors=(ErrorRecord(
                timestamp=datetime.now(),
                step_index=-1,
                tool_name=tool_call.tool_name,
                error_type="execution_error",
                error_message=error_msg,
                retry_count=max_retries,
                resolved=False,
            ),),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_llm(self, messages: list[dict]) -> str:
        """通过 LLMClient 调用 LLM（OpenAI 兼容格式）。"""
        return await self._llm.chat(messages)

    def _parse_thought(self, raw: str, current_step: int, total_steps: int) -> Thought:
        """解析 LLM 思考结果。"""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse thought JSON: %s", text[:200])
            # Default to finish if we can't parse
            return Thought(
                action="finish",
                reasoning=f"无法解析 LLM 响应，终止执行: {text[:100]}",
                tool_call=None,
                next_step=current_step,
                message=Message(role="assistant", content=text),
            )

        action = data.get("action", "finish")
        reasoning = data.get("reasoning", "")

        tool_call = None
        next_step = current_step
        if action == "call_tool":
            tool_name = data.get("tool_name", "")
            tool_args = data.get("tool_args", {})
            tool_call = ToolCall(tool_name=tool_name, arguments=dict(tool_args))
            next_step = min(current_step + 1, total_steps)

        return Thought(
            action=action,
            reasoning=reasoning,
            tool_call=tool_call,
            next_step=next_step,
            message=Message(role="assistant", content=reasoning),
        )
