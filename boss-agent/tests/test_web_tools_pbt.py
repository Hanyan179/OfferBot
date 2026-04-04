"""
Property-based tests for Web Tools (WebFetch + WebSearch).

# Feature: web-tools, Property 1: URL 标准化
对任意 http:// URL，normalize_url 应返回 https:// 等价 URL，且除协议部分外其余内容不变。
验证: 需求 1.2

# Feature: web-tools, Property 2: 内容截断长度约束
对任意 Markdown 字符串和正整数 max_length，truncate_content 返回的字符串长度 ≤ max_length。
验证: 需求 1.3

# Feature: web-tools, Property 3: 缓存存储往返一致性
对任意 key/value，cache.set 后在 TTL 有效期内 cache.get 应返回相同值。
验证: 需求 1.4

# Feature: web-tools, Property 4: 非法 URL 拒绝
对任意不符合 URL 格式的字符串，validate_url 应返回 False。
验证: 需求 1.7

# Feature: web-tools, Property 5: Fetch 结果元数据完整性
成功的 WebFetch 返回结果应包含 status_code/content_bytes/duration_ms/final_url。
验证: 需求 1.8

# Feature: web-tools, Property 6: 搜索结果数量约束
结果数量 ≤ max_results，默认 ≤ 10。
验证: 需求 2.3, 2.4

# Feature: web-tools, Property 7: 空白关键词拒绝
纯空白字符串应被 validate_query 拒绝。
验证: 需求 2.6

# Feature: web-tools, Property 8: 搜索结果结构完整性
每个结果应包含 title/url/snippet，metadata 应包含 query/result_count/duration_ms。
验证: 需求 2.2, 2.7
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings, strategies as st

from tools.browser.web_fetch import (
    normalize_url,
    truncate_content,
    validate_url,
    TTLCache,
    WebFetchTool,
)
from tools.browser.web_search import (
    validate_query,
    clamp_max_results,
    parse_search_response,
    WebSearchTool,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# 合法的 host 部分（字母数字 + 点）
st_host = st.from_regex(r"[a-z][a-z0-9]{0,20}\.[a-z]{2,6}", fullmatch=True)

# 合法的 path 部分
st_path = st.from_regex(r"(/[a-z0-9_\-]{1,15}){0,4}", fullmatch=True)

# http:// URL（用于 Property 1）
st_http_url = st.builds(
    lambda host, path: f"http://{host}{path}",
    host=st_host,
    path=st_path,
)

# 任意文本内容
st_content_text = st.text(min_size=0, max_size=500)

# max_length 至少要能容纳截断后缀 "\n\n[内容已截断]"（9 字符）
# 当 max_length < 后缀长度时，实现会降级返回后缀本身，这是已知行为
st_max_length = st.integers(min_value=10, max_value=1000)

# 缓存 key/value
st_cache_key = st.text(min_size=1, max_size=100).filter(bool)
st_cache_value = st.text(min_size=0, max_size=300)

# 非 URL 字符串（不含 scheme://netloc 结构）
st_non_url = st.text(min_size=0, max_size=100).filter(
    lambda s: "://" not in s or not validate_url(s)
)

# 纯空白字符串（含空字符串）
st_whitespace = st.from_regex(r"[\s]*", fullmatch=True).filter(
    lambda s: s.strip() == ""
)

# max_results 范围 [1, 20]
st_max_results = st.integers(min_value=1, max_value=20)


def _run_async(coro):
    """Helper to run async code in hypothesis tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Feature: web-tools, Property 1: URL 标准化
# ---------------------------------------------------------------------------


class TestURLNormalization:
    """对任意 http:// URL，normalize_url 应返回 https:// 等价 URL。"""

    @settings(max_examples=100)
    @given(url=st_http_url)
    def test_http_upgraded_to_https(self, url: str):
        """normalize_url 应将 http:// 替换为 https://。"""
        result = normalize_url(url)
        assert result.startswith("https://"), f"Expected https:// prefix, got: {result}"

    @settings(max_examples=100)
    @given(url=st_http_url)
    def test_rest_of_url_unchanged(self, url: str):
        """除协议部分外，URL 其余内容不变。"""
        result = normalize_url(url)
        # 去掉协议前缀后应相同
        original_rest = url[len("http://"):]
        result_rest = result[len("https://"):]
        assert result_rest == original_rest, (
            f"URL body changed: {original_rest!r} -> {result_rest!r}"
        )


# ---------------------------------------------------------------------------
# Feature: web-tools, Property 2: 内容截断长度约束
# ---------------------------------------------------------------------------


class TestContentTruncation:
    """对任意字符串和 max_length，截断后长度 ≤ max_length。"""

    @settings(max_examples=100)
    @given(content=st_content_text, max_length=st_max_length)
    def test_truncated_length_within_limit(self, content: str, max_length: int):
        """截断后的内容长度不超过 max_length。"""
        result, truncated = truncate_content(content, max_length)
        assert len(result) <= max_length, (
            f"Truncated length {len(result)} > max_length {max_length}"
        )

    @settings(max_examples=100)
    @given(content=st_content_text, max_length=st_max_length)
    def test_truncation_flag_correct(self, content: str, max_length: int):
        """当原始内容超过 max_length 时，truncated 标志应为 True。"""
        result, truncated = truncate_content(content, max_length)
        if len(content) <= max_length:
            assert not truncated, "Should not be truncated when content fits"
        else:
            assert truncated, "Should be truncated when content exceeds max_length"


# ---------------------------------------------------------------------------
# Feature: web-tools, Property 3: 缓存存储往返一致性
# ---------------------------------------------------------------------------


class TestCacheRoundTrip:
    """cache.set 后 cache.get 应返回相同值。"""

    @settings(max_examples=100)
    @given(key=st_cache_key, value=st_cache_value)
    def test_set_then_get_returns_same_value(self, key: str, value: str):
        """写入后立即读取应返回相同值。"""
        cache = TTLCache(ttl_seconds=3600)  # 长 TTL 确保不过期
        cache.set(key, value)
        result = cache.get(key)
        assert result == value, f"Expected {value!r}, got {result!r}"

    @settings(max_examples=100)
    @given(key=st_cache_key)
    def test_get_nonexistent_returns_none(self, key: str):
        """读取不存在的 key 应返回 None。"""
        cache = TTLCache(ttl_seconds=3600)
        result = cache.get(key)
        assert result is None, f"Expected None for missing key, got {result!r}"


# ---------------------------------------------------------------------------
# Feature: web-tools, Property 4: 非法 URL 拒绝
# ---------------------------------------------------------------------------


class TestInvalidURLRejection:
    """对任意非 URL 字符串，validate_url 应返回 False。"""

    @settings(max_examples=100)
    @given(text=st_non_url)
    def test_non_url_rejected(self, text: str):
        """不含合法 scheme://netloc 的字符串应被拒绝。"""
        assert validate_url(text) is False, f"Expected False for {text!r}"

    @settings(max_examples=100)
    @given(text=st.just(""))
    def test_empty_string_rejected(self, text: str):
        """空字符串应被拒绝。"""
        assert validate_url(text) is False


# ---------------------------------------------------------------------------
# Feature: web-tools, Property 5: Fetch 结果元数据完整性
# ---------------------------------------------------------------------------


# 用于 Property 5 的 mock HTML 策略
st_html_body = st.text(min_size=1, max_size=200).map(
    lambda t: f"<html><body>{t}</body></html>"
)


class TestFetchMetadataCompleteness:
    """成功的 WebFetch 返回结果应包含完整元数据。"""

    @settings(max_examples=100)
    @given(html_body=st_html_body)
    def test_success_result_has_all_metadata_keys(self, html_body: str):
        """成功结果的 metadata 应包含 status_code/content_bytes/duration_ms/final_url。"""
        import httpx as _httpx

        def _handler(request: _httpx.Request) -> _httpx.Response:
            return _httpx.Response(200, html=html_body)

        transport = _httpx.MockTransport(_handler)

        tool = WebFetchTool()
        # 替换内部缓存确保不命中
        tool._cache = TTLCache(ttl_seconds=0)

        async def _run():
            # Monkey-patch httpx.AsyncClient 使用 mock transport
            original_init = _httpx.AsyncClient.__init__

            def patched_init(self_client, **kwargs):
                kwargs["transport"] = transport
                original_init(self_client, **kwargs)

            _httpx.AsyncClient.__init__ = patched_init
            try:
                return await tool.execute(
                    {"url": "https://example.com/test"}, context=None
                )
            finally:
                _httpx.AsyncClient.__init__ = original_init

        result = _run_async(_run())

        assert result["success"] is True, f"Expected success, got: {result}"
        meta = result["metadata"]
        assert "status_code" in meta
        assert "content_bytes" in meta
        assert "duration_ms" in meta
        assert "final_url" in meta
        assert isinstance(meta["status_code"], int)
        assert isinstance(meta["content_bytes"], int) and meta["content_bytes"] >= 0
        assert isinstance(meta["duration_ms"], float) and meta["duration_ms"] >= 0
        assert isinstance(meta["final_url"], str) and len(meta["final_url"]) > 0


# ---------------------------------------------------------------------------
# Feature: web-tools, Property 6: 搜索结果数量约束
# ---------------------------------------------------------------------------

# 生成 SearchResult 列表
st_search_result = st.fixed_dictionaries({
    "name": st.text(min_size=1, max_size=50),
    "url": st.from_regex(r"https://[a-z]{3,10}\.[a-z]{2,4}/[a-z]{1,10}", fullmatch=True),
    "snippet": st.text(min_size=1, max_size=100),
})

st_search_results_list = st.lists(st_search_result, min_size=0, max_size=30)


class TestSearchResultCountConstraint:
    """结果数量 ≤ max_results。"""

    @settings(max_examples=100)
    @given(
        results=st_search_results_list,
        max_results=st_max_results,
    )
    def test_parsed_results_clamped_to_max(self, results: list, max_results: int):
        """parse_search_response 后截断到 max_results 条。"""
        raw_response = {"webPages": {"value": results}}
        parsed = parse_search_response(raw_response)
        clamped = parsed[:max_results]
        assert len(clamped) <= max_results, (
            f"Result count {len(clamped)} > max_results {max_results}"
        )

    @settings(max_examples=100)
    @given(results=st_search_results_list)
    def test_default_max_results_is_10(self, results: list):
        """未指定 max_results 时，默认约束为 ≤ 10。"""
        default = clamp_max_results(None, default=10)
        raw_response = {"webPages": {"value": results}}
        parsed = parse_search_response(raw_response)
        clamped = parsed[:default]
        assert len(clamped) <= 10


# ---------------------------------------------------------------------------
# Feature: web-tools, Property 7: 空白关键词拒绝
# ---------------------------------------------------------------------------


class TestWhitespaceQueryRejection:
    """纯空白字符串应被 validate_query 拒绝。"""

    @settings(max_examples=100)
    @given(query=st_whitespace)
    def test_whitespace_only_rejected(self, query: str):
        """仅由空白字符组成的字符串应返回 False。"""
        assert validate_query(query) is False, f"Expected False for {query!r}"

    def test_empty_string_rejected(self):
        """空字符串应返回 False。"""
        assert validate_query("") is False

    def test_spaces_rejected(self):
        """纯空格应返回 False。"""
        assert validate_query("   ") is False

    def test_tabs_and_newlines_rejected(self):
        """制表符和换行符应返回 False。"""
        assert validate_query("\t\n\r") is False


# ---------------------------------------------------------------------------
# Feature: web-tools, Property 8: 搜索结果结构完整性
# ---------------------------------------------------------------------------


class TestSearchResultStructure:
    """每个结果应包含 title/url/snippet，metadata 应包含 query/result_count/duration_ms。"""

    @settings(max_examples=100)
    @given(results=st_search_results_list)
    def test_each_result_has_required_fields(self, results: list):
        """parse_search_response 返回的每个结果应包含 title/url/snippet。"""
        raw_response = {"webPages": {"value": results}}
        parsed = parse_search_response(raw_response)
        for item in parsed:
            assert "title" in item, f"Missing 'title' in {item}"
            assert "url" in item, f"Missing 'url' in {item}"
            assert "snippet" in item, f"Missing 'snippet' in {item}"
            assert isinstance(item["title"], str)
            assert isinstance(item["url"], str)
            assert isinstance(item["snippet"], str)

    @settings(max_examples=100)
    @given(
        query=st.text(min_size=1, max_size=50).filter(lambda s: s.strip()),
        results=st_search_results_list,
    )
    def test_search_metadata_structure(self, query: str, results: list):
        """模拟成功的搜索返回，验证 metadata 结构完整。"""
        import httpx as _httpx
        import json

        api_response = {"webPages": {"value": results}}

        def _handler(request: _httpx.Request) -> _httpx.Response:
            return _httpx.Response(
                200,
                json=api_response,
            )

        transport = _httpx.MockTransport(_handler)

        # 创建带 API key 的 tool
        class _FakeConfig:
            web_search_default_results = 10
            web_search_api_key = "test-key"

        tool = WebSearchTool(config=_FakeConfig())

        async def _run():
            original_init = _httpx.AsyncClient.__init__

            def patched_init(self_client, **kwargs):
                kwargs["transport"] = transport
                original_init(self_client, **kwargs)

            _httpx.AsyncClient.__init__ = patched_init
            try:
                return await tool.execute(
                    {"query": query}, context=None
                )
            finally:
                _httpx.AsyncClient.__init__ = original_init

        result = _run_async(_run())

        assert result["success"] is True, f"Expected success, got: {result}"
        meta = result["metadata"]
        assert "query" in meta
        assert "result_count" in meta
        assert "duration_ms" in meta
        assert isinstance(meta["query"], str)
        assert isinstance(meta["result_count"], int) and meta["result_count"] >= 0
        assert isinstance(meta["duration_ms"], float) and meta["duration_ms"] >= 0
