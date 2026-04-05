"""
Property-Based Tests: ConversationManager

Feature: framework-core-fixes
Properties 1-4: 消息持久化 round-trip, 对话摘要提取, 对话列表按时间倒序, 删除对话后不可见

使用 Hypothesis 生成随机数据，验证 ConversationManager 的核心正确性属性。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from agent.conversation_manager import ConversationManager
from tools.data.chat_history import ChatHistoryStore


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

def _make_manager(tmp_path: Path) -> tuple[ConversationManager, ChatHistoryStore]:
    """创建临时目录下的 ConversationManager + ChatHistoryStore。"""
    store = ChatHistoryStore(base_dir=str(tmp_path))
    return ConversationManager(store), store


def _run(coro):
    """在同步测试中运行 async 函数。"""
    return asyncio.run(coro)


# Strategies
st_role = st.sampled_from(["user", "assistant"])
st_content = st.text(min_size=1, max_size=200)
st_message = st.fixed_dictionaries({"role": st_role, "content": st_content})
st_messages = st.lists(st_message, min_size=1, max_size=20)

# 至少包含一条 user 消息的消息列表
st_messages_with_user = st.lists(st_message, min_size=1, max_size=20).filter(
    lambda msgs: any(m["role"] == "user" for m in msgs)
)


# ---------------------------------------------------------------------------
# Property 1: 消息持久化 round-trip
# Validates: Requirements 1.2, 3.1, 3.2, 3.3
# ---------------------------------------------------------------------------

class TestMessageRoundTrip:
    """Feature: framework-core-fixes, Property 1: 消息持久化 round-trip"""

    @given(messages=st_messages)
    @settings(max_examples=100)
    def test_save_then_load_preserves_messages(
        self, messages: list[dict[str, str]]
    ) -> None:
        """保存消息后加载，数量、role、content 和顺序应一致。"""
        with tempfile.TemporaryDirectory() as tmp:
            mgr, store = _make_manager(Path(tmp))

            conv = _run(mgr.create_conversation())
            conv_id = conv["id"]

            # 保存所有消息
            for msg in messages:
                _run(store.save_message(conv_id, msg["role"], msg["content"]))

            # 加载并验证
            loaded = _run(mgr.get_conversation_messages(conv_id))

            assert len(loaded) == len(messages)
            for original, restored in zip(messages, loaded):
                assert restored["role"] == original["role"]
                assert restored["content"] == original["content"]


# ---------------------------------------------------------------------------
# Property 2: 对话摘要提取
# Validates: Requirements 2.1
# ---------------------------------------------------------------------------

class TestConversationSummary:
    """Feature: framework-core-fixes, Property 2: 对话摘要提取"""

    @given(messages=st_messages_with_user)
    @settings(max_examples=100)
    def test_summary_is_first_user_message_prefix(
        self, messages: list[dict[str, str]]
    ) -> None:
        """摘要应等于首条 user 消息 content 的前 50 个字符。"""
        with tempfile.TemporaryDirectory() as tmp:
            mgr, store = _make_manager(Path(tmp))

            conv = _run(mgr.create_conversation())
            conv_id = conv["id"]

            for msg in messages:
                _run(store.save_message(conv_id, msg["role"], msg["content"]))

            summary = _run(mgr.get_conversation_summary(conv_id))

            # 找到首条 user 消息
            first_user_content = next(
                m["content"] for m in messages if m["role"] == "user"
            )
            expected = first_user_content[:50]
            assert summary == expected


# ---------------------------------------------------------------------------
# Property 3: 对话列表按时间倒序
# Validates: Requirements 2.2
# ---------------------------------------------------------------------------

class TestConversationListOrder:
    """Feature: framework-core-fixes, Property 3: 对话列表按时间倒序"""

    @given(count=st.integers(min_value=1, max_value=8))
    @settings(max_examples=50)
    def test_list_conversations_reverse_chronological(self, count: int) -> None:
        """list_conversations 返回的列表应按创建时间倒序排列。"""
        from datetime import datetime, timedelta

        with tempfile.TemporaryDirectory() as tmp:
            mgr, store = _make_manager(Path(tmp))

            # 直接创建带不同时间戳的 .jsonl 文件，避免秒级精度冲突
            base_time = datetime(2025, 1, 1, 10, 0, 0)
            store._ensure_dir()
            created_ids = []
            for i in range(count):
                dt = base_time + timedelta(seconds=i)
                conv_id = dt.strftime("%Y-%m-%dT%H-%M-%S")
                filepath = store._conversation_path(conv_id)
                filepath.touch(exist_ok=True)
                created_ids.append(conv_id)

            conversations = _run(mgr.list_conversations())

            assert len(conversations) == count
            # 验证倒序：每个相邻元素的 created_at 前者 >= 后者
            for i in range(len(conversations) - 1):
                assert conversations[i]["created_at"] >= conversations[i + 1]["created_at"]


# ---------------------------------------------------------------------------
# Property 4: 删除对话后不可见
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------

class TestDeleteConversation:
    """Feature: framework-core-fixes, Property 4: 删除对话后不可见"""

    @given(messages=st_messages)
    @settings(max_examples=100)
    def test_deleted_conversation_not_in_list(
        self, messages: list[dict[str, str]]
    ) -> None:
        """删除对话后，该 ID 不应出现在列表中，文件也不应存在。"""
        with tempfile.TemporaryDirectory() as tmp:
            mgr, store = _make_manager(Path(tmp))

            conv = _run(mgr.create_conversation())
            conv_id = conv["id"]

            # 写入一些消息
            for msg in messages:
                _run(store.save_message(conv_id, msg["role"], msg["content"]))

            # 删除
            result = _run(mgr.delete_conversation(conv_id))
            assert result is True

            # 验证不在列表中
            conversations = _run(mgr.list_conversations())
            listed_ids = [c["id"] for c in conversations]
            assert conv_id not in listed_ids

            # 验证文件不存在
            filepath = store._conversation_path(conv_id)
            assert not filepath.exists()
