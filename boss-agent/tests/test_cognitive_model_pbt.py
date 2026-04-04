"""
Property-based test for GetUserCognitiveModelTool.

Property 4: 用户认知模型覆盖所有非空分类
get_user_cognitive_model 返回的摘要应包含所有非空文件内容，不包含空文件分类。
验证: 需求 3.4
"""

from __future__ import annotations

import asyncio
import tempfile

from hypothesis import given, settings, strategies as st

from tools.data.memory_tools import (
    CATEGORY_FILE_MAP,
    SaveMemoryTool,
    GetMemoryTool,
    GetUserCognitiveModelTool,
)

# ---------------------------------------------------------------------------
# Strategies (reuse patterns from test_memory_tools_pbt.py)
# ---------------------------------------------------------------------------

st_predefined_category = st.sampled_from(list(CATEGORY_FILE_MAP.keys()))

_printable_no_control = st.characters(
    categories=("L", "M", "N", "P", "S", "Z"),
    exclude_characters="#\n\r",
)

st_title = (
    st.text(alphabet=_printable_no_control, min_size=1, max_size=60)
    .filter(lambda s: s.strip())
)

st_content = (
    st.text(alphabet=_printable_no_control, min_size=1, max_size=200)
    .filter(lambda s: s.strip())
)

# 生成 1~5 个 (category, title, content) 条目，分类从预定义列表中选
st_entries = st.lists(
    st.tuples(st_predefined_category, st_title, st_content),
    min_size=1,
    max_size=5,
)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Property 4: 用户认知模型覆盖所有非空分类
# ---------------------------------------------------------------------------


class TestUserCognitiveModelCoverage:
    """
    Property 4: 用户认知模型覆盖所有非空分类

    For any set of memory entries across categories,
    get_user_cognitive_model should include content from all non-empty
    categories and exclude empty categories.

    Validates: Requirements 3.4
    """

    @given(entries=st_entries)
    @settings(max_examples=50, deadline=5000)
    def test_summary_includes_all_nonempty_categories(
        self, entries: list[tuple[str, str, str]]
    ):
        """Summary should contain content from every category that has entries."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                ctx = {"memory_dir": tmp}
                save_tool = SaveMemoryTool()
                cognitive_tool = GetUserCognitiveModelTool()

                # Save all entries
                written_categories: set[str] = set()
                written_contents: list[str] = []
                for category, title, content in entries:
                    await save_tool.execute(
                        {"category": category, "title": title, "content": content},
                        ctx,
                    )
                    written_categories.add(category)
                    written_contents.append(content)

                # Get cognitive model
                result = await cognitive_tool.execute({}, ctx)
                summary = result["summary"]
                included = result["categories_included"]

                # All written categories should be included
                for cat in written_categories:
                    assert cat in included, (
                        f"Category '{cat}' has entries but not in included list"
                    )

                # All written content should appear in summary
                for content in written_contents:
                    assert content in summary, (
                        f"Content not found in summary: {content[:50]}..."
                    )

        _run_async(_test())

    @given(entries=st_entries)
    @settings(max_examples=30, deadline=5000)
    def test_empty_categories_excluded(
        self, entries: list[tuple[str, str, str]]
    ):
        """Categories with no entries should not appear in the cognitive model."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                ctx = {"memory_dir": tmp}
                save_tool = SaveMemoryTool()
                cognitive_tool = GetUserCognitiveModelTool()

                # Save entries (only to some categories)
                written_categories: set[str] = set()
                for category, title, content in entries:
                    await save_tool.execute(
                        {"category": category, "title": title, "content": content},
                        ctx,
                    )
                    written_categories.add(category)

                result = await cognitive_tool.execute({}, ctx)
                included = set(result["categories_included"])

                # No extra categories should be included
                assert included == written_categories, (
                    f"Included {included} but only wrote to {written_categories}"
                )

        _run_async(_test())

    def test_empty_dir_returns_empty_summary(self):
        """Cognitive model on empty memory dir returns empty summary."""

        async def _test():
            with tempfile.TemporaryDirectory() as tmp:
                ctx = {"memory_dir": tmp}
                cognitive_tool = GetUserCognitiveModelTool()

                result = await cognitive_tool.execute({}, ctx)
                assert result["summary"] == ""
                assert result["categories_included"] == []

        _run_async(_test())

    def test_nonexistent_dir_returns_empty(self):
        """Cognitive model on nonexistent dir returns empty summary."""

        async def _test():
            ctx = {"memory_dir": "/tmp/nonexistent_memory_dir_test_12345"}
            cognitive_tool = GetUserCognitiveModelTool()

            result = await cognitive_tool.execute({}, ctx)
            assert result["summary"] == ""
            assert result["categories_included"] == []

        _run_async(_test())
