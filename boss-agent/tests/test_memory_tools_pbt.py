"""
Property-based tests for Memory Tools.

Property 1: 记忆存储往返一致性
对任意有效记忆条目，save_memory 写入后 get_memory 读取应包含该条目的标题和内容。
验证: 需求 1.3, 4.1

Property 2: 记忆文件按分类隔离
写入分类 A 的条目不应出现在分类 B 的文件中。
验证: 需求 1.3

Property 3: search_memory 关键词匹配正确性
返回的每条结果应包含搜索关键词，且所有包含该关键词的文件内容都应出现在结果中。
验证: 需求 3.2

Property 5: update_memory 局部更新正确性
更新后其他条目不变。
验证: 需求 4.2

Property 6: delete_memory 不影响其他条目
删除后其他条目不变。
验证: 需求 4.3

Property 7: list_memory_categories 计数正确性
计数等于 ## 标题实际数量。
验证: 需求 4.5
"""

from __future__ import annotations

import asyncio
import tempfile

from hypothesis import given, settings, strategies as st

from tools.data.memory_tools import (
    CATEGORY_FILE_MAP,
    SaveMemoryTool,
    GetMemoryTool,
    SearchMemoryTool,
    UpdateMemoryTool,
    DeleteMemoryTool,
    ListMemoryCategoryTool,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# 分类策略：预定义分类 + 自定义分类
st_predefined_category = st.sampled_from(list(CATEGORY_FILE_MAP.keys()))
st_custom_category = st.from_regex(r"[a-z][a-z0-9_]{1,19}", fullmatch=True).filter(
    lambda c: c not in CATEGORY_FILE_MAP
)
st_category = st.one_of(st_predefined_category, st_custom_category)

# 可打印字符集（排除控制字符如 \r \x00 等，排除 ## 和换行避免干扰 Markdown 解析）
_printable_no_control = st.characters(
    categories=("L", "M", "N", "P", "S", "Z"),
    exclude_characters="#\n\r",
)

# 非空标题：单行，无 ## 和控制字符
st_title = (
    st.text(alphabet=_printable_no_control, min_size=1, max_size=60)
    .filter(lambda s: s.strip())
)

# 非空内容：可多行但不含 ## 和控制字符
st_content = (
    st.text(alphabet=_printable_no_control, min_size=1, max_size=200)
    .filter(lambda s: s.strip())
)


def _run_async(coro):
    """Helper to run async code in hypothesis tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Property 1: 记忆存储往返一致性
# ---------------------------------------------------------------------------


class TestMemoryRoundTrip:
    """
    Property 1: 记忆存储往返一致性

    For any valid memory entry (arbitrary category, non-empty title, non-empty content),
    after save_memory writes it, get_memory should return content containing
    that entry's title and content text.

    Validates: Requirements 1.3, 4.1
    """

    @given(category=st_category, title=st_title, content=st_content)
    @settings(max_examples=100)
    def test_save_then_get_contains_entry(self, category: str, title: str, content: str):
        """
        Property 1: 记忆存储往返一致性
        save_memory 写入后 get_memory 读取应包含该条目的标题和内容。
        """
        save_tool = SaveMemoryTool()
        get_tool = GetMemoryTool()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                await save_tool.execute(
                    {"category": category, "title": title, "content": content},
                    context,
                )
                return await get_tool.execute({"category": category}, context)

            result = _run_async(_run())

            # 返回的文件内容应包含标题和内容
            assert result["category"] == category
            assert title in result["content"]
            assert content in result["content"]
            assert result["entries"] >= 1

    @given(
        category=st_category,
        entries=st.lists(
            st.tuples(st_title, st_content),
            min_size=2,
            max_size=5,
            unique_by=lambda t: t[0],  # 标题唯一
        ),
    )
    @settings(max_examples=50)
    def test_multiple_saves_all_present(self, category: str, entries: list[tuple[str, str]]):
        """
        Property 1 扩展: 多条记忆写入同一分类后，所有条目都应出现在 get_memory 结果中。
        """
        save_tool = SaveMemoryTool()
        get_tool = GetMemoryTool()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                for title, content in entries:
                    await save_tool.execute(
                        {"category": category, "title": title, "content": content},
                        context,
                    )
                return await get_tool.execute({"category": category}, context)

            result = _run_async(_run())

            for title, content in entries:
                assert title in result["content"], f"标题 '{title}' 未出现在 get_memory 结果中"
                assert content in result["content"], f"内容 '{content}' 未出现在 get_memory 结果中"

            assert result["entries"] == len(entries)


# ---------------------------------------------------------------------------
# Property 2: 记忆文件按分类隔离
# ---------------------------------------------------------------------------


class TestMemoryCategoryIsolation:
    """
    Property 2: 记忆文件按分类隔离

    写入分类 A 的条目不应出现在分类 B 的文件中。
    每个分类对应独立的 Markdown 文件，跨分类不会互相污染。

    Validates: Requirements 1.3
    """

    @given(
        categories=st.tuples(st_category, st_category).filter(lambda t: t[0] != t[1]),
        title=st_title,
        content=st_content,
    )
    @settings(max_examples=100)
    def test_different_categories_isolated(
        self,
        categories: tuple[str, str],
        title: str,
        content: str,
    ):
        """
        Property 2: 记忆文件按分类隔离
        写入分类 A 的条目后，get_memory 读取分类 B 不应包含该条目的标题和内容。
        """
        cat_a, cat_b = categories
        save_tool = SaveMemoryTool()
        get_tool = GetMemoryTool()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                # 写入分类 A
                await save_tool.execute(
                    {"category": cat_a, "title": title, "content": content},
                    context,
                )
                # 读取分类 B
                return await get_tool.execute({"category": cat_b}, context)

            result = _run_async(_run())

            # 分类 B 应该为空（没有写入过）
            assert result["entries"] == 0
            assert result["content"] == ""

    @given(
        categories=st.tuples(st_category, st_category).filter(lambda t: t[0] != t[1]),
        entries_a=st.lists(
            st.tuples(st_title, st_content),
            min_size=1,
            max_size=3,
            unique_by=lambda t: t[0],
        ),
    )
    @settings(max_examples=50)
    def test_save_to_one_category_other_empty(
        self,
        categories: tuple[str, str],
        entries_a: list[tuple[str, str]],
    ):
        """
        Property 2 扩展: 向分类 A 写入多条记忆后，分类 B 仍应为空（entries=0）。
        """
        cat_a, cat_b = categories
        save_tool = SaveMemoryTool()
        get_tool = GetMemoryTool()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                for title, content in entries_a:
                    await save_tool.execute(
                        {"category": cat_a, "title": title, "content": content},
                        context,
                    )
                return await get_tool.execute({"category": cat_b}, context)

            result = _run_async(_run())

            assert result["entries"] == 0, (
                f"分类 '{cat_b}' 应为空，但发现 {result['entries']} 条记忆"
            )
            assert result["content"] == ""


# ---------------------------------------------------------------------------
# Property 3: search_memory 关键词匹配正确性
# ---------------------------------------------------------------------------

# 关键词策略：至少 2 个字符的可打印文本（避免单字符误匹配溯源元数据等）
st_keyword = (
    st.text(alphabet=_printable_no_control, min_size=2, max_size=20)
    .filter(lambda s: s.strip())
)


class TestSearchMemoryKeywordCorrectness:
    """
    Property 3: search_memory 关键词匹配正确性

    返回的每条结果应包含搜索关键词（不区分大小写），
    且所有包含该关键词的已保存条目都应出现在结果中。

    Validates: Requirements 3.2
    """

    @given(
        category=st_category,
        entries=st.lists(
            st.tuples(st_title, st_content),
            min_size=1,
            max_size=5,
            unique_by=lambda t: t[0],
        ),
        keyword=st_keyword,
    )
    @settings(max_examples=100)
    def test_all_results_contain_keyword(
        self,
        category: str,
        entries: list[tuple[str, str]],
        keyword: str,
    ):
        """
        Property 3a: search_memory 返回的每条结果都应包含搜索关键词（不区分大小写）。
        """
        save_tool = SaveMemoryTool()
        search_tool = SearchMemoryTool()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                for title, content in entries:
                    await save_tool.execute(
                        {"category": category, "title": title, "content": content},
                        context,
                    )
                return await search_tool.execute({"keyword": keyword}, context)

            result = _run_async(_run())
            kw_lower = keyword.lower()

            for item in result["results"]:
                match_in_title = kw_lower in item["title"].lower()
                match_in_content = kw_lower in item["content"].lower()
                assert match_in_title or match_in_content, (
                    f"搜索结果条目 '{item['title']}' 的标题和内容均不包含关键词 '{keyword}'"
                )

    @given(
        category=st_category,
        entries=st.lists(
            st.tuples(st_title, st_content),
            min_size=1,
            max_size=5,
            unique_by=lambda t: t[0],
        ),
    )
    @settings(max_examples=100)
    def test_no_matching_entries_missed(
        self,
        category: str,
        entries: list[tuple[str, str]],
    ):
        """
        Property 3b: 所有包含关键词的已保存条目都应出现在 search_memory 结果中。
        使用第一条记忆的标题作为搜索关键词，确保至少有一条匹配。
        """
        save_tool = SaveMemoryTool()
        search_tool = SearchMemoryTool()

        # 用第一条记忆的标题（stripped，与 _parse_sections 行为一致）作为关键词
        keyword = entries[0][0].strip()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                for title, content in entries:
                    await save_tool.execute(
                        {"category": category, "title": title, "content": content},
                        context,
                    )
                return await search_tool.execute({"keyword": keyword}, context)

            result = _run_async(_run())
            kw_lower = keyword.lower()
            result_titles = {item["title"] for item in result["results"]}

            # 所有标题或内容包含关键词的条目都应出现在结果中
            # 注意：_parse_sections 会 strip 标题，所以用 stripped 版本比较
            for title, content in entries:
                stripped_title = title.strip()
                if kw_lower in stripped_title.lower() or kw_lower in content.lower():
                    assert stripped_title in result_titles, (
                        f"条目 '{stripped_title}' 包含关键词 '{keyword}' 但未出现在搜索结果中"
                    )

    @given(
        categories=st.lists(
            st_predefined_category,
            min_size=2,
            max_size=3,
            unique=True,
        ),
        title=st_title,
        content=st_content,
    )
    @settings(max_examples=50)
    def test_search_spans_all_categories(
        self,
        categories: list[str],
        title: str,
        content: str,
    ):
        """
        Property 3c: search_memory 应跨所有分类文件搜索。
        同一条目写入多个分类后，搜索标题应在每个分类中都找到匹配。
        """
        save_tool = SaveMemoryTool()
        search_tool = SearchMemoryTool()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                for cat in categories:
                    await save_tool.execute(
                        {"category": cat, "title": title, "content": content},
                        context,
                    )
                return await search_tool.execute({"keyword": title}, context)

            result = _run_async(_run())
            result_categories = {item["category"] for item in result["results"]}

            for cat in categories:
                assert cat in result_categories, (
                    f"分类 '{cat}' 中包含关键词 '{title}' 但未出现在搜索结果中"
                )


# ---------------------------------------------------------------------------
# Property 5: update_memory 局部更新正确性
# ---------------------------------------------------------------------------


class TestUpdateMemoryPreservesOthers:
    """
    Property 5: update_memory 局部更新正确性

    For any set of memory entries in the same category, updating one entry's
    content should leave all other entries unchanged.

    Validates: Requirements 4.2
    """

    @given(
        category=st_category,
        entries=st.lists(
            st.tuples(st_title, st_content),
            min_size=2,
            max_size=5,
            unique_by=lambda t: t[0].strip(),
        ),
        new_content=st_content,
    )
    @settings(max_examples=100)
    def test_update_preserves_other_entries(
        self,
        category: str,
        entries: list[tuple[str, str]],
        new_content: str,
    ):
        """
        Property 5: 更新某条记忆后，同文件中的其他条目标题和内容应保持不变。
        """
        save_tool = SaveMemoryTool()
        get_tool = GetMemoryTool()
        update_tool = UpdateMemoryTool()

        # _parse_sections strips titles, so use stripped version
        target_title = entries[0][0].strip()
        other_entries = entries[1:]

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                # Save all entries
                for title, content in entries:
                    await save_tool.execute(
                        {"category": category, "title": title, "content": content},
                        context,
                    )
                # Update the target entry
                result = await update_tool.execute(
                    {"category": category, "title": target_title, "new_content": new_content},
                    context,
                )
                assert result["updated"] is True
                # Read back
                return await get_tool.execute({"category": category}, context)

            result = _run_async(_run())
            file_content = result["content"]

            # Updated entry should have new content
            assert new_content in file_content

            # Other entries should still be present with original content
            for title, content in other_entries:
                assert title in file_content, (
                    f"条目 '{title}' 在 update 后消失了"
                )
                assert content in file_content, (
                    f"条目 '{title}' 的原始内容在 update 后被改变了"
                )

    @given(
        category=st_category,
        entries=st.lists(
            st.tuples(st_title, st_content),
            min_size=2,
            max_size=5,
            unique_by=lambda t: t[0].strip(),
        ),
        new_content=st_content,
    )
    @settings(max_examples=50)
    def test_update_entry_count_unchanged(
        self,
        category: str,
        entries: list[tuple[str, str]],
        new_content: str,
    ):
        """
        Property 5 扩展: update 后条目总数不变。
        """
        save_tool = SaveMemoryTool()
        get_tool = GetMemoryTool()
        update_tool = UpdateMemoryTool()

        target_title = entries[0][0].strip()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                for title, content in entries:
                    await save_tool.execute(
                        {"category": category, "title": title, "content": content},
                        context,
                    )
                await update_tool.execute(
                    {"category": category, "title": target_title, "new_content": new_content},
                    context,
                )
                return await get_tool.execute({"category": category}, context)

            result = _run_async(_run())
            assert result["entries"] == len(entries), (
                f"update 后条目数从 {len(entries)} 变为 {result['entries']}"
            )


# ---------------------------------------------------------------------------
# Property 6: delete_memory 不影响其他条目
# ---------------------------------------------------------------------------


class TestDeleteMemoryPreservesOthers:
    """
    Property 6: delete_memory 不影响其他条目

    For any set of memory entries in the same category, deleting one entry
    should leave all other entries unchanged and the deleted entry should
    no longer appear in get_memory results.

    Validates: Requirements 4.3
    """

    @given(
        category=st_category,
        entries=st.lists(
            st.tuples(st_title, st_content),
            min_size=2,
            max_size=5,
            unique_by=lambda t: t[0].strip(),
        ),
    )
    @settings(max_examples=100)
    def test_delete_preserves_other_entries(
        self,
        category: str,
        entries: list[tuple[str, str]],
    ):
        """
        Property 6: 删除某条记忆后，其他条目标题和内容应保持不变。
        """
        save_tool = SaveMemoryTool()
        get_tool = GetMemoryTool()
        delete_tool = DeleteMemoryTool()

        # _parse_sections strips titles, so use stripped version for delete
        target_title = entries[0][0].strip()
        other_entries = entries[1:]

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                for title, content in entries:
                    await save_tool.execute(
                        {"category": category, "title": title, "content": content},
                        context,
                    )
                result = await delete_tool.execute(
                    {"category": category, "title": target_title},
                    context,
                )
                assert result["deleted"] is True
                return await get_tool.execute({"category": category}, context)

            result = _run_async(_run())

            from tools.data.memory_tools import _parse_sections
            remaining_titles = {s["title"] for s in _parse_sections(result["content"])}

            # Deleted entry should be gone
            assert target_title not in remaining_titles, (
                f"已删除的条目 '{target_title}' 仍出现在文件中"
            )

            # Other entries should still be present with original content
            file_content = result["content"]
            for title, content in other_entries:
                stripped = title.strip()
                assert stripped in remaining_titles, (
                    f"条目 '{stripped}' 在 delete 后消失了"
                )
                assert content in file_content, (
                    f"条目 '{stripped}' 的原始内容在 delete 后被改变了"
                )

    @given(
        category=st_category,
        entries=st.lists(
            st.tuples(st_title, st_content),
            min_size=2,
            max_size=5,
            unique_by=lambda t: t[0].strip(),
        ),
    )
    @settings(max_examples=50)
    def test_delete_reduces_entry_count_by_one(
        self,
        category: str,
        entries: list[tuple[str, str]],
    ):
        """
        Property 6 扩展: delete 后条目数减少 1。
        """
        save_tool = SaveMemoryTool()
        get_tool = GetMemoryTool()
        delete_tool = DeleteMemoryTool()

        target_title = entries[0][0].strip()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                for title, content in entries:
                    await save_tool.execute(
                        {"category": category, "title": title, "content": content},
                        context,
                    )
                await delete_tool.execute(
                    {"category": category, "title": target_title},
                    context,
                )
                return await get_tool.execute({"category": category}, context)

            result = _run_async(_run())
            assert result["entries"] == len(entries) - 1, (
                f"delete 后条目数应为 {len(entries) - 1}，实际为 {result['entries']}"
            )


# ---------------------------------------------------------------------------
# Property 7: list_memory_categories 计数正确性
# ---------------------------------------------------------------------------


class TestListMemoryCategoriesCount:
    """
    Property 7: list_memory_categories 计数正确性

    For any set of memory files, list_memory_categories should return
    entry counts equal to the actual number of ## headings in each file.

    Validates: Requirements 4.5
    """

    @given(
        data=st.lists(
            st.tuples(
                st_predefined_category,
                st.lists(
                    st.tuples(st_title, st_content),
                    min_size=1,
                    max_size=5,
                    unique_by=lambda t: t[0],
                ),
            ),
            min_size=1,
            max_size=4,
            unique_by=lambda t: t[0],  # unique categories
        ),
    )
    @settings(max_examples=100)
    def test_category_counts_match_headings(
        self,
        data: list[tuple[str, list[tuple[str, str]]]],
    ):
        """
        Property 7: list_memory_categories 返回的每个分类条目数等于文件中 ## 标题的实际数量。
        """
        save_tool = SaveMemoryTool()
        list_tool = ListMemoryCategoryTool()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            # Build expected counts
            expected: dict[str, int] = {}
            for category, entries in data:
                expected[category] = len(entries)

            async def _run():
                for category, entries in data:
                    for title, content in entries:
                        await save_tool.execute(
                            {"category": category, "title": title, "content": content},
                            context,
                        )
                return await list_tool.execute({}, context)

            result = _run_async(_run())
            actual = {c["category"]: c["entries"] for c in result["categories"]}

            for category, count in expected.items():
                assert actual.get(category) == count, (
                    f"分类 '{category}' 期望 {count} 条，实际 {actual.get(category)}"
                )

    @given(
        category=st_predefined_category,
        entries=st.lists(
            st.tuples(st_title, st_content),
            min_size=1,
            max_size=5,
            unique_by=lambda t: t[0],
        ),
    )
    @settings(max_examples=50)
    def test_single_category_count(
        self,
        category: str,
        entries: list[tuple[str, str]],
    ):
        """
        Property 7 扩展: 单分类写入 N 条后，list 返回该分类计数为 N。
        """
        save_tool = SaveMemoryTool()
        list_tool = ListMemoryCategoryTool()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                for title, content in entries:
                    await save_tool.execute(
                        {"category": category, "title": title, "content": content},
                        context,
                    )
                return await list_tool.execute({}, context)

            result = _run_async(_run())
            cats = {c["category"]: c["entries"] for c in result["categories"]}

            assert cats[category] == len(entries), (
                f"分类 '{category}' 期望 {len(entries)} 条，实际 {cats.get(category)}"
            )

    @given(
        category=st_predefined_category,
        entries=st.lists(
            st.tuples(st_title, st_content),
            min_size=2,
            max_size=5,
            unique_by=lambda t: t[0].strip(),
        ),
    )
    @settings(max_examples=50)
    def test_count_after_delete(
        self,
        category: str,
        entries: list[tuple[str, str]],
    ):
        """
        Property 7 扩展: 删除一条后，list 返回的计数应减少 1。
        """
        save_tool = SaveMemoryTool()
        delete_tool = DeleteMemoryTool()
        list_tool = ListMemoryCategoryTool()

        target_title = entries[0][0].strip()

        with tempfile.TemporaryDirectory() as tmp_dir:
            context = {"memory_dir": tmp_dir}

            async def _run():
                for title, content in entries:
                    await save_tool.execute(
                        {"category": category, "title": title, "content": content},
                        context,
                    )
                await delete_tool.execute(
                    {"category": category, "title": target_title},
                    context,
                )
                return await list_tool.execute({}, context)

            result = _run_async(_run())
            cats = {c["category"]: c["entries"] for c in result["categories"]}

            assert cats[category] == len(entries) - 1, (
                f"删除后分类 '{category}' 期望 {len(entries) - 1} 条，实际 {cats.get(category)}"
            )
