"""
MemoryExtractor 单元测试

验证：
- 提取 prompt 包含正确的分类列表和规则
- extract 方法正确调用 Memory Tools（save_memory / update_memory）
- 多轮工具调用（先 get_memory 再 save_memory）
- 无可提取信息时不调用工具
- conversation_id 自动注入
- 工具参数解析失败时的容错
- 最大轮数限制
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.memory_extractor import (
    EXTRACT_PROMPT,
    MemoryExtractor,
    _ALLOWED_TOOLS,
    _MAX_EXTRACT_TURNS,
)
from tools.data.memory_tools import CATEGORY_FILE_MAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call(
    tool_name: str,
    arguments: dict,
    call_id: str = "call_1",
) -> SimpleNamespace:
    """构造一个模拟的 OpenAI tool_call 对象。"""
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=tool_name,
            arguments=json.dumps(arguments, ensure_ascii=False),
        ),
    )


def _make_llm_response(
    tool_calls: list | None = None,
    content: str | None = None,
) -> SimpleNamespace:
    """构造一个模拟的 LLM ChatCompletionMessage 响应。"""
    return SimpleNamespace(
        tool_calls=tool_calls,
        content=content,
    )


# ---------------------------------------------------------------------------
# 提取 Prompt 验证
# ---------------------------------------------------------------------------

class TestExtractPrompt:
    """验证 EXTRACT_PROMPT 包含正确的分类列表和规则。"""

    def test_prompt_contains_all_predefined_categories(self):
        """提取 prompt 的 {categories} 占位符应包含所有预定义分类。"""
        extractor = MemoryExtractor(llm_client=MagicMock())
        categories_text = extractor._build_categories_text()
        for eng_name in CATEGORY_FILE_MAP:
            assert eng_name in categories_text, f"分类 '{eng_name}' 未出现在 categories 文本中"

    def test_prompt_contains_chinese_names(self):
        """分类列表应同时包含中文名称。"""
        extractor = MemoryExtractor(llm_client=MagicMock())
        categories_text = extractor._build_categories_text()
        for cn_file in CATEGORY_FILE_MAP.values():
            cn_name = cn_file.removesuffix(".md")
            assert cn_name in categories_text, f"中文名 '{cn_name}' 未出现在 categories 文本中"

    def test_prompt_template_has_placeholders(self):
        """EXTRACT_PROMPT 应包含 {categories} 和 {conversation} 占位符。"""
        assert "{categories}" in EXTRACT_PROMPT
        assert "{conversation}" in EXTRACT_PROMPT

    def test_prompt_contains_key_rules(self):
        """提取 prompt 应包含关键规则指引。"""
        assert "get_memory" in EXTRACT_PROMPT
        assert "save_memory" in EXTRACT_PROMPT
        assert "update_memory" in EXTRACT_PROMPT

    def test_prompt_instructs_no_text_reply(self):
        """提取 prompt 应指示不输出文本回复，只通过工具调用保存。"""
        assert "不要输出任何文本回复" in EXTRACT_PROMPT


# ---------------------------------------------------------------------------
# MemoryExtractor 初始化
# ---------------------------------------------------------------------------

class TestExtractorInit:
    """验证 MemoryExtractor 初始化和内部 ToolRegistry。"""

    def test_tool_registry_contains_all_allowed_tools(self):
        extractor = MemoryExtractor(llm_client=MagicMock())
        for tool_name in _ALLOWED_TOOLS:
            assert extractor._tool_registry.has_tool(tool_name)

    def test_tool_registry_count(self):
        extractor = MemoryExtractor(llm_client=MagicMock())
        assert extractor._tool_registry.tool_count == len(_ALLOWED_TOOLS)


# ---------------------------------------------------------------------------
# extract 方法 — 核心流程
# ---------------------------------------------------------------------------

class TestExtract:
    """验证 extract 方法的核心流程。"""

    @pytest.mark.asyncio
    async def test_empty_messages_returns_immediately(self):
        """空消息列表应直接返回，不调用 LLM。"""
        llm = AsyncMock()
        extractor = MemoryExtractor(llm_client=llm)
        await extractor.extract([], context={})
        llm.chat_with_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_user_messages_returns_immediately(self):
        """只有 system 消息（无 user/assistant）应直接返回。"""
        llm = AsyncMock()
        extractor = MemoryExtractor(llm_client=llm)
        await extractor.extract(
            [{"role": "system", "content": "你是助手"}],
            context={},
        )
        llm.chat_with_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_save_memory_call(self):
        """LLM 返回一个 save_memory tool_call 时，应执行该工具。"""
        save_args = {
            "category": "personal_thoughts",
            "title": "想去大厂",
            "content": "想在大厂 AI 团队待两年",
        }
        tc = _make_tool_call("save_memory", save_args, call_id="call_save_1")

        llm = AsyncMock()
        # 第一次调用返回 tool_calls，第二次返回空（结束循环）
        llm.chat_with_tools.side_effect = [
            _make_llm_response(tool_calls=[tc]),
            _make_llm_response(tool_calls=None),
        ]

        extractor = MemoryExtractor(llm_client=llm)
        # Mock _execute_tool 来验证调用
        extractor._execute_tool = AsyncMock(return_value={"status": "ok"})

        messages = [
            {"role": "user", "content": "我想去大厂 AI 团队待两年"},
            {"role": "assistant", "content": "了解你的想法"},
        ]
        await extractor.extract(messages, context={"conversation_id": "conv-001"})

        extractor._execute_tool.assert_called_once()
        call_args = extractor._execute_tool.call_args
        assert call_args[0][0] == "save_memory"
        # 验证 conversation_id 被自动注入
        assert call_args[0][1]["source_conversation_id"] == "conv-001"

    @pytest.mark.asyncio
    async def test_conversation_id_auto_injected(self):
        """save_memory 调用应自动注入 source_conversation_id。"""
        save_args = {
            "category": "career_planning",
            "title": "目标方向",
            "content": "想做 Agent 方向",
        }
        tc = _make_tool_call("save_memory", save_args)

        llm = AsyncMock()
        llm.chat_with_tools.side_effect = [
            _make_llm_response(tool_calls=[tc]),
            _make_llm_response(tool_calls=None),
        ]

        extractor = MemoryExtractor(llm_client=llm)
        extractor._execute_tool = AsyncMock(return_value={"status": "ok"})

        await extractor.extract(
            [{"role": "user", "content": "我想做 Agent 方向"}],
            context={"conversation_id": "conv-xyz"},
        )

        tool_args = extractor._execute_tool.call_args[0][1]
        assert tool_args["source_conversation_id"] == "conv-xyz"

    @pytest.mark.asyncio
    async def test_conversation_id_not_overwritten_if_present(self):
        """如果 LLM 已提供 source_conversation_id，不应覆盖。"""
        save_args = {
            "category": "personal_thoughts",
            "title": "测试",
            "content": "内容",
            "source_conversation_id": "llm-provided-id",
        }
        tc = _make_tool_call("save_memory", save_args)

        llm = AsyncMock()
        llm.chat_with_tools.side_effect = [
            _make_llm_response(tool_calls=[tc]),
            _make_llm_response(tool_calls=None),
        ]

        extractor = MemoryExtractor(llm_client=llm)
        extractor._execute_tool = AsyncMock(return_value={"status": "ok"})

        await extractor.extract(
            [{"role": "user", "content": "测试"}],
            context={"conversation_id": "ctx-id"},
        )

        tool_args = extractor._execute_tool.call_args[0][1]
        assert tool_args["source_conversation_id"] == "llm-provided-id"

    @pytest.mark.asyncio
    async def test_no_tool_calls_means_nothing_extracted(self):
        """LLM 不返回 tool_calls 时，不应执行任何工具。"""
        llm = AsyncMock()
        llm.chat_with_tools.return_value = _make_llm_response(tool_calls=None)

        extractor = MemoryExtractor(llm_client=llm)
        extractor._execute_tool = AsyncMock()

        await extractor.extract(
            [{"role": "user", "content": "今天天气不错"}],
            context={},
        )

        extractor._execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_turn_get_then_save(self):
        """多轮调用：LLM 先 get_memory 检查，再 save_memory 保存。"""
        get_tc = _make_tool_call("get_memory", {"category": "personal_thoughts"}, call_id="call_get")
        save_tc = _make_tool_call(
            "save_memory",
            {"category": "personal_thoughts", "title": "新想法", "content": "详细内容"},
            call_id="call_save",
        )

        llm = AsyncMock()
        llm.chat_with_tools.side_effect = [
            # 第一轮：先读取已有记忆
            _make_llm_response(tool_calls=[get_tc]),
            # 第二轮：保存新记忆
            _make_llm_response(tool_calls=[save_tc]),
            # 第三轮：结束
            _make_llm_response(tool_calls=None),
        ]

        extractor = MemoryExtractor(llm_client=llm)
        extractor._execute_tool = AsyncMock(return_value={"content": ""})

        await extractor.extract(
            [{"role": "user", "content": "我有个新想法"}],
            context={"conversation_id": "conv-multi"},
        )

        assert extractor._execute_tool.call_count == 2
        first_call = extractor._execute_tool.call_args_list[0]
        second_call = extractor._execute_tool.call_args_list[1]
        assert first_call[0][0] == "get_memory"
        assert second_call[0][0] == "save_memory"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_single_response(self):
        """单次 LLM 响应包含多个 tool_calls 时，应全部执行。"""
        tc1 = _make_tool_call(
            "save_memory",
            {"category": "personal_thoughts", "title": "想法1", "content": "内容1"},
            call_id="call_1",
        )
        tc2 = _make_tool_call(
            "save_memory",
            {"category": "hobbies_interests", "title": "爱好1", "content": "内容2"},
            call_id="call_2",
        )

        llm = AsyncMock()
        llm.chat_with_tools.side_effect = [
            _make_llm_response(tool_calls=[tc1, tc2]),
            _make_llm_response(tool_calls=None),
        ]

        extractor = MemoryExtractor(llm_client=llm)
        extractor._execute_tool = AsyncMock(return_value={"status": "ok"})

        await extractor.extract(
            [{"role": "user", "content": "我喜欢编程，也想去大厂"}],
            context={},
        )

        assert extractor._execute_tool.call_count == 2

    @pytest.mark.asyncio
    async def test_update_memory_call(self):
        """LLM 返回 update_memory tool_call 时，应正确执行。"""
        tc = _make_tool_call(
            "update_memory",
            {"category": "career_planning", "title": "目标城市", "new_content": "想去深圳"},
            call_id="call_update",
        )

        llm = AsyncMock()
        llm.chat_with_tools.side_effect = [
            _make_llm_response(tool_calls=[tc]),
            _make_llm_response(tool_calls=None),
        ]

        extractor = MemoryExtractor(llm_client=llm)
        extractor._execute_tool = AsyncMock(return_value={"status": "ok"})

        await extractor.extract(
            [{"role": "user", "content": "我改主意了，想去深圳"}],
            context={},
        )

        call_args = extractor._execute_tool.call_args
        assert call_args[0][0] == "update_memory"
        assert call_args[0][1]["new_content"] == "想去深圳"


# ---------------------------------------------------------------------------
# 错误处理与边界情况
# ---------------------------------------------------------------------------

class TestExtractErrorHandling:
    """验证 extract 方法的错误处理。"""

    @pytest.mark.asyncio
    async def test_llm_exception_does_not_raise(self):
        """LLM 调用抛异常时，extract 应静默返回，不向上抛出。"""
        llm = AsyncMock()
        llm.chat_with_tools.side_effect = Exception("API 超时")

        extractor = MemoryExtractor(llm_client=llm)
        # 不应抛出异常
        await extractor.extract(
            [{"role": "user", "content": "测试"}],
            context={},
        )

    @pytest.mark.asyncio
    async def test_invalid_tool_arguments_handled(self):
        """工具参数 JSON 解析失败时，应跳过该调用并继续。"""
        bad_tc = SimpleNamespace(
            id="call_bad",
            function=SimpleNamespace(
                name="save_memory",
                arguments="这不是合法的JSON{{{",
            ),
        )

        llm = AsyncMock()
        llm.chat_with_tools.side_effect = [
            _make_llm_response(tool_calls=[bad_tc]),
            _make_llm_response(tool_calls=None),
        ]

        extractor = MemoryExtractor(llm_client=llm)
        extractor._execute_tool = AsyncMock()

        await extractor.extract(
            [{"role": "user", "content": "测试"}],
            context={},
        )

        # 参数解析失败，不应调用 _execute_tool
        extractor._execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_turns_limit(self):
        """达到最大轮数时应停止，不无限循环。"""
        tc = _make_tool_call("get_memory", {"category": "personal_thoughts"})

        llm = AsyncMock()
        # 每轮都返回 tool_calls，模拟无限循环场景
        llm.chat_with_tools.return_value = _make_llm_response(tool_calls=[tc])

        extractor = MemoryExtractor(llm_client=llm)
        extractor._execute_tool = AsyncMock(return_value={"content": ""})

        await extractor.extract(
            [{"role": "user", "content": "测试"}],
            context={},
        )

        # 应恰好调用 _MAX_EXTRACT_TURNS 轮
        assert llm.chat_with_tools.call_count == _MAX_EXTRACT_TURNS

    @pytest.mark.asyncio
    async def test_unknown_tool_name_handled(self):
        """LLM 返回未知工具名时，_execute_tool 应返回错误而不崩溃。"""
        llm = MagicMock()
        extractor = MemoryExtractor(llm_client=llm)

        result = await extractor._execute_tool("nonexistent_tool", {}, {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_tool_execution_exception_handled(self):
        """工具执行抛异常时，_execute_tool 应返回错误 dict。"""
        llm = MagicMock()
        extractor = MemoryExtractor(llm_client=llm)

        # Mock 一个会抛异常的工具
        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = RuntimeError("磁盘满了")
        extractor._tool_registry.get_tool = MagicMock(return_value=mock_tool)

        result = await extractor._execute_tool("save_memory", {}, {})
        assert "error" in result
        assert "磁盘满了" in result["error"]

    @pytest.mark.asyncio
    async def test_default_conversation_id_when_missing(self):
        """context 中没有 conversation_id 时，应使用默认值 'unknown'。"""
        save_args = {
            "category": "personal_thoughts",
            "title": "测试",
            "content": "内容",
        }
        tc = _make_tool_call("save_memory", save_args)

        llm = AsyncMock()
        llm.chat_with_tools.side_effect = [
            _make_llm_response(tool_calls=[tc]),
            _make_llm_response(tool_calls=None),
        ]

        extractor = MemoryExtractor(llm_client=llm)
        extractor._execute_tool = AsyncMock(return_value={"status": "ok"})

        # context 不含 conversation_id
        await extractor.extract(
            [{"role": "user", "content": "测试"}],
            context={},
        )

        tool_args = extractor._execute_tool.call_args[0][1]
        assert tool_args["source_conversation_id"] == "unknown"


# ---------------------------------------------------------------------------
# _format_conversation 验证
# ---------------------------------------------------------------------------

class TestFormatConversation:
    """验证对话格式化逻辑。"""

    def test_user_and_assistant_messages(self):
        extractor = MemoryExtractor(llm_client=MagicMock())
        result = extractor._format_conversation([
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀"},
        ])
        assert "用户: 你好" in result
        assert "助手: 你好呀" in result

    def test_system_messages_excluded(self):
        extractor = MemoryExtractor(llm_client=MagicMock())
        result = extractor._format_conversation([
            {"role": "system", "content": "系统消息"},
            {"role": "user", "content": "你好"},
        ])
        assert "系统消息" not in result
        assert "用户: 你好" in result

    def test_tool_messages_excluded(self):
        extractor = MemoryExtractor(llm_client=MagicMock())
        result = extractor._format_conversation([
            {"role": "tool", "content": "工具结果"},
            {"role": "user", "content": "你好"},
        ])
        assert "工具结果" not in result

    def test_empty_messages(self):
        extractor = MemoryExtractor(llm_client=MagicMock())
        result = extractor._format_conversation([])
        assert result == ""
