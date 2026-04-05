"""
Memory Extractor — 记忆提取子 Agent

参考 Claude Code extractMemories.ts 设计：
每轮对话结束后异步运行独立的 LLM 调用，从对话中提取用户信息，
通过 Memory Tools 写入记忆文件。不干扰主对话线程。

核心流程：
1. 接收最近的对话消息
2. 用独立 LLM 调用 + 提取 prompt + Memory Tools schema
3. LLM 返回 tool_calls（save_memory / update_memory）
4. 执行 tool_calls 写入记忆文件
5. 如果 LLM 需要先读已有记忆（get_memory），支持多轮工具调用
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.llm_client import LLMClient
from agent.tool_registry import ToolRegistry
from tools.data.memory_tools import (
    SaveMemoryTool,
    GetMemoryTool,
    SearchMemoryTool,
    UpdateMemoryTool,
    DeleteMemoryTool,
    GetUserCognitiveModelTool,
    CATEGORY_FILE_MAP,
)

logger = logging.getLogger(__name__)

# 子 Agent 允许使用的 Memory Tools
_ALLOWED_TOOLS: dict[str, type] = {
    "save_memory": SaveMemoryTool,
    "get_memory": GetMemoryTool,
    "search_memory": SearchMemoryTool,
    "update_memory": UpdateMemoryTool,
    "delete_memory": DeleteMemoryTool,
    "get_user_cognitive_model": GetUserCognitiveModelTool,
}

EXTRACT_PROMPT = """\
你是一个记忆提取助手。你的唯一任务是分析对话内容，提取用户的个人信息并保存到记忆系统。

## 可用分类

{categories}

## 已有记忆（当前状态）

{existing_memory}

## 核心原则：更新优先，避免膨胀

记忆系统的目标是维护一份**精炼、准确、无重复**的用户画像，不是对话日志。
上面的"已有记忆"就是当前所有记忆的标题列表，你必须基于它来决策。

## 决策规则

对比对话中的新信息和已有记忆，选择正确的操作：

| 情况 | 操作 |
|------|------|
| 已有记忆中有相同或相似主题的条目 | **update_memory** — 用合并后的完整内容替换旧条目 |
| 已有记忆中无相关条目，且信息有价值 | **save_memory** — 新增 |
| 信息已存在且无变化 | **不操作** |
| 多个条目内容重叠 | **delete_memory** 删旧 + **save_memory** 写合并版 |

## 写入要求
- update_memory 时：title 必须与已有条目的标题**完全一致**（从上面的已有记忆中复制）
- save_memory 时：title 要具体（如"目标城市偏好"而非"求职信息"）
- 每个分类下同一主题**只保留一个条目**

## 不要提取的内容
- 简历中的结构化字段（姓名、电话、邮箱等）— 这些在数据库里
- 用户的临时性提问（"帮我搜岗位"不是记忆）
- AI 的回复内容

## 要提取的内容
- 想法、目标、偏好、价值观
- 求职策略变化
- 性格特征、沟通风格
- 对特定事物的态度

## 对话内容

{conversation}

## 执行

分析上面的对话，如果有值得提取的信息，直接调用 save_memory 或 update_memory。
如果需要查看某个已有条目的详细内容再决定如何合并，可以先调用 get_memory(category)。
如果对话中没有值得提取的信息，不要调用任何工具。
"""

# 子 Agent 最大工具调用轮数（防止无限循环）
_MAX_EXTRACT_TURNS = 5


class MemoryExtractor:
    """
    记忆提取子 Agent。

    在主 Agent 回复完成后异步调用，读取最近的对话内容，
    识别可提取的用户信息，调用 Memory Tools 写入记忆文件。
    不干扰主对话线程。
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client
        self._tool_registry = self._build_tool_registry()

    @staticmethod
    def _build_tool_registry() -> ToolRegistry:
        """构建子 Agent 专用的 ToolRegistry，只包含 Memory Tools。"""
        registry = ToolRegistry()
        for tool_cls in _ALLOWED_TOOLS.values():
            registry.register(tool_cls())
        return registry

    def _build_categories_text(self) -> str:
        """生成分类列表文本，注入到提取 prompt 中。"""
        lines = []
        for eng, cn_file in CATEGORY_FILE_MAP.items():
            cn_name = cn_file.removesuffix(".md")
            lines.append(f"- {eng}（{cn_name}）")
        return "\n".join(lines)

    def _format_conversation(self, messages: list[dict]) -> str:
        """将对话消息格式化为可读文本。只保留 user 和 assistant 消息。"""
        parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                parts.append(f"用户: {content}")
            elif role == "assistant":
                parts.append(f"助手: {content}")
        return "\n\n".join(parts)

    async def _load_existing_memory_summary(self, context: dict[str, Any]) -> str:
        """程序层预读所有已有记忆的标题列表，供 prompt 注入。"""
        tool = self._tool_registry.get_tool("get_user_cognitive_model")
        if tool is None:
            return ""
        try:
            result = await tool.execute({}, context)
            return result.get("summary", "")
        except Exception as e:
            logger.warning("预读记忆摘要失败: %s", e)
            return ""

    async def extract(
        self,
        recent_messages: list[dict],
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        从最近的对话消息中提取记忆，异步执行。

        使用独立的 LLM 调用（不是主对话的一部分），传入对话内容 +
        提取 prompt + Memory Tools schema。支持多轮工具调用：
        LLM 可以先 get_memory 检查已有记忆，再决定 save 还是 update。

        Args:
            recent_messages: 最近的对话消息列表（OpenAI 格式）
            context: 上下文（包含 memory_dir 等配置，传递给 Tool.execute）
        """
        if not recent_messages:
            return

        ctx = context or {}

        # 从 context 获取 conversation_id，注入到 save_memory 调用中
        conversation_id = ctx.get("conversation_id", "unknown")

        # 构建提取 prompt
        categories_text = self._build_categories_text()
        conversation_text = self._format_conversation(recent_messages)

        if not conversation_text.strip():
            return

        # 程序层预读已有记忆摘要，直接注入 prompt
        existing_memory = await self._load_existing_memory_summary(ctx)

        prompt = EXTRACT_PROMPT.format(
            categories=categories_text,
            existing_memory=existing_memory or "（暂无记忆）",
            conversation=conversation_text,
        )

        # 构建工具定义
        tools = self._tool_registry.get_all_schemas()

        # 初始消息
        messages: list[dict] = [
            {"role": "system", "content": prompt},
        ]

        # 多轮工具调用循环
        for turn in range(_MAX_EXTRACT_TURNS):
            try:
                response = await self._llm.chat_with_tools(
                    messages=messages,
                    tools=tools,
                )
            except Exception as e:
                logger.error("MemoryExtractor LLM 调用失败: %s", e, exc_info=True)
                return

            tool_calls = response.tool_calls or []

            # 没有工具调用 → 提取完成
            if not tool_calls:
                text = response.content or ""
                logger.info("MemoryExtractor 第 %d 轮: 无工具调用，提取结束。LLM 回复: %s", turn + 1, text[:200] if text else "(空)")
                return

            logger.info("MemoryExtractor 第 %d 轮: %d 个工具调用", turn + 1, len(tool_calls))

            # 把 assistant 消息（含 tool_calls）加入历史
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if response.content:
                assistant_msg["content"] = response.content
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ]
            messages.append(assistant_msg)

            # 执行每个工具调用
            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    logger.warning("无法解析工具参数: %s", tc.function.arguments[:200])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({"error": "参数解析失败"}, ensure_ascii=False),
                    })
                    continue

                # 自动注入 source_conversation_id
                if tool_name == "save_memory" and "source_conversation_id" not in tool_args:
                    tool_args["source_conversation_id"] = conversation_id

                result = await self._execute_tool(tool_name, tool_args, ctx)
                logger.info("MemoryExtractor 工具 '%s' 执行结果: %s", tool_name, str(result)[:200])
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

        logger.warning("MemoryExtractor 达到最大轮数 %d，停止提取", _MAX_EXTRACT_TURNS)

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: dict,
        context: dict[str, Any],
    ) -> dict:
        """执行单个 Memory Tool，返回结果 dict。"""
        tool = self._tool_registry.get_tool(tool_name)
        if tool is None:
            logger.warning("MemoryExtractor: 未知工具 '%s'", tool_name)
            return {"error": f"未知工具: {tool_name}"}

        try:
            result = await tool.execute(tool_args, context)
            if not isinstance(result, dict):
                result = {"result": result}
            return result
        except Exception as e:
            logger.error("MemoryExtractor 工具 '%s' 执行失败: %s", tool_name, e)
            return {"error": str(e)}
