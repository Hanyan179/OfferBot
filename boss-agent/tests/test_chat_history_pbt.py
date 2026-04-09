"""
Property-based tests for Chat History Store.

Property 8: 对话消息存储往返一致性
逐条 save_message 后 load_history 应得到顺序一致、role/content 一致的消息列表。
验证: 需求 5.3

Property 9: 对话历史加载数量约束
N > MAX_RESTORE_MESSAGES 时，load_history 返回数量等于 MAX_RESTORE_MESSAGES。
验证: 需求 5.6
"""

from __future__ import annotations

import asyncio
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from tools.data.chat_history import ChatHistoryStore

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

st_role = st.sampled_from(["user", "assistant", "system", "tool"])

# 消息内容：非空可打印文本
st_content = st.text(
    alphabet=st.characters(categories=("L", "M", "N", "P", "S", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: s.strip())

# 单条消息：(role, content)
st_message = st.tuples(st_role, st_content)

# 消息序列：1~20 条
st_messages = st.lists(st_message, min_size=1, max_size=20)


def _run_async(coro):
    """Helper to run async code in hypothesis tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Property 8: 对话消息存储往返一致性
# ---------------------------------------------------------------------------


class TestChatHistoryRoundTrip:
    """
    Property 8: 对话消息存储往返一致性

    For any sequence of messages, after save_message writes them one by one,
    load_history should return messages in the same order with matching
    role and content.

    Validates: Requirements 5.3
    """

    @given(messages=st_messages)
    @settings(max_examples=50, deadline=5000)
    def test_save_then_load_preserves_order_and_content(
        self, messages: list[tuple[str, str]]
    ):
        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                store = ChatHistoryStore(base_dir=tmp)
                cid = await store.create_conversation()

                for role, content in messages:
                    await store.save_message(cid, role, content)

                loaded = await store.load_history(cid, limit=len(messages) + 10)

                assert len(loaded) == len(messages), (
                    f"Expected {len(messages)} messages, got {len(loaded)}"
                )
                for i, ((exp_role, exp_content), actual) in enumerate(
                    zip(messages, loaded)
                ):
                    assert actual["role"] == exp_role, (
                        f"Message {i}: expected role={exp_role}, got {actual['role']}"
                    )
                    assert actual["content"] == exp_content, (
                        f"Message {i}: content mismatch"
                    )

        _run_async(_test())

    @given(messages=st_messages)
    @settings(max_examples=50, deadline=5000)
    def test_each_message_has_timestamp(self, messages: list[tuple[str, str]]):
        """Every saved message should have a timestamp field."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                store = ChatHistoryStore(base_dir=tmp)
                cid = await store.create_conversation()

                for role, content in messages:
                    await store.save_message(cid, role, content)

                loaded = await store.load_history(cid, limit=len(messages) + 10)

                for i, msg in enumerate(loaded):
                    assert "timestamp" in msg, (
                        f"Message {i} missing timestamp"
                    )

        _run_async(_test())

    @given(
        role=st_role,
        content=st_content,
        metadata=st.fixed_dictionaries({"tool": st.text(min_size=1, max_size=20)}),
    )
    @settings(max_examples=30, deadline=5000)
    def test_metadata_preserved(self, role: str, content: str, metadata: dict):
        """Metadata passed to save_message should appear in loaded messages."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                store = ChatHistoryStore(base_dir=tmp)
                cid = await store.create_conversation()

                await store.save_message(cid, role, content, metadata=metadata)

                loaded = await store.load_history(cid)
                assert len(loaded) == 1
                assert loaded[0]["metadata"] == metadata

        _run_async(_test())


# ---------------------------------------------------------------------------
# Property 9: 对话历史加载数量约束
# ---------------------------------------------------------------------------


class TestChatHistoryLoadLimit:
    """
    Property 9: 对话历史加载数量约束

    When N > MAX_RESTORE_MESSAGES, load_history returns exactly
    MAX_RESTORE_MESSAGES messages (the most recent ones).

    Validates: Requirements 5.6
    """

    @given(
        extra_count=st.integers(min_value=1, max_value=50),
        role=st_role,
        content=st_content,
    )
    @settings(max_examples=20, deadline=30000)
    def test_load_respects_max_restore_limit(
        self, extra_count: int, role: str, content: str
    ):
        """With N > limit messages, load_history returns exactly limit messages."""

        # Use a small limit to keep tests fast
        small_limit = 5

        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                store = ChatHistoryStore(base_dir=tmp)
                cid = await store.create_conversation()

                total = small_limit + extra_count
                for i in range(total):
                    await store.save_message(cid, role, f"{content}_{i}")

                loaded = await store.load_history(cid, limit=small_limit)

                assert len(loaded) == small_limit, (
                    f"Expected {small_limit}, got {len(loaded)}"
                )
                # Should be the LAST small_limit messages
                for j, msg in enumerate(loaded):
                    expected_idx = total - small_limit + j
                    assert msg["content"] == f"{content}_{expected_idx}"

        _run_async(_test())

    @given(
        n=st.integers(min_value=1, max_value=10),
        role=st_role,
        content=st_content,
    )
    @settings(max_examples=20, deadline=10000)
    def test_load_under_limit_returns_all(
        self, n: int, role: str, content: str
    ):
        """When N <= limit, load_history returns all N messages."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                store = ChatHistoryStore(base_dir=tmp)
                cid = await store.create_conversation()

                for i in range(n):
                    await store.save_message(cid, role, f"{content}_{i}")

                loaded = await store.load_history(cid, limit=n + 100)
                assert len(loaded) == n

        _run_async(_test())

    def test_default_limit_is_max_restore_messages(self):
        """load_history without explicit limit uses MAX_RESTORE_MESSAGES."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                store = ChatHistoryStore(base_dir=tmp)
                store.MAX_RESTORE_MESSAGES = 3  # override for test speed
                cid = await store.create_conversation()

                for i in range(10):
                    await store.save_message(cid, "user", f"msg_{i}")

                loaded = await store.load_history(cid)
                assert len(loaded) == 3
                # Should be the last 3
                assert loaded[0]["content"] == "msg_7"
                assert loaded[1]["content"] == "msg_8"
                assert loaded[2]["content"] == "msg_9"

        _run_async(_test())


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestChatHistoryEdgeCases:
    """Additional edge case tests for ChatHistoryStore."""

    def test_get_active_conversation_returns_latest(self):
        """get_active_conversation_id returns the most recent conversation."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                store = ChatHistoryStore(base_dir=tmp)

                cid1 = await store.create_conversation()
                # Small delay to ensure different timestamps
                import time
                time.sleep(1.1)
                cid2 = await store.create_conversation()

                active = await store.get_active_conversation_id()
                assert active == cid2

        _run_async(_test())

    def test_nonexistent_conversation_returns_empty(self):
        """load_history for a nonexistent conversation returns empty list."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                store = ChatHistoryStore(base_dir=tmp)
                loaded = await store.load_history("nonexistent-id")
                assert loaded == []

        _run_async(_test())

    def test_empty_dir_returns_no_active(self):
        """get_active_conversation_id on empty/nonexistent dir returns None."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                store = ChatHistoryStore(base_dir=tmp + "/does_not_exist")
                active = await store.get_active_conversation_id()
                assert active is None

        _run_async(_test())
