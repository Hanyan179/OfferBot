"""
WebSearchTool 单元测试

测试搜索 API 错误处理、API Key 未配置场景、Tool ABC 接口合规。
使用 httpx.MockTransport mock 搜索 API 响应。

需求: 2.5, 3.2, 3.3, 3.4, 3.7
"""

from __future__ import annotations

import asyncio

import httpx

from agent.tool_registry import Tool
from tools.browser.web_search import WebSearchTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockConfig:
    """简单 mock config，用于设置 API Key。"""

    def __init__(self, api_key: str = "test-api-key", default_results: int = 10):
        self.web_search_api_key = api_key
        self.web_search_default_results = default_results


def _run_async(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_bing_response(results: list[dict] | None = None) -> dict:
    """构造 Bing API 格式的搜索响应。"""
    if results is None:
        results = [
            {"name": "Result 1", "url": "https://example.com/1", "snippet": "Snippet 1"},
            {"name": "Result 2", "url": "https://example.com/2", "snippet": "Snippet 2"},
        ]
    return {"webPages": {"value": results}}


async def _execute_with_mock(
    tool: WebSearchTool,
    transport: httpx.MockTransport,
    params: dict | None = None,
) -> dict:
    """Execute tool with monkey-patched AsyncClient to use mock transport."""
    if params is None:
        params = {"query": "test search"}

    original_init = httpx.AsyncClient.__init__

    def patched_init(self_client, **kwargs):
        kwargs["transport"] = transport
        original_init(self_client, **kwargs)

    httpx.AsyncClient.__init__ = patched_init
    try:
        return await tool.execute(params, context=None)
    finally:
        httpx.AsyncClient.__init__ = original_init


# ---------------------------------------------------------------------------
# Tests: Tool ABC 接口合规 (Requirements 3.2, 3.3, 3.4, 3.7)
# ---------------------------------------------------------------------------


class TestWebSearchToolABCCompliance:
    """验证 WebSearchTool 正确实现 Tool ABC 接口。"""

    def test_inherits_from_tool(self):
        """WebSearchTool 应继承 Tool ABC。"""
        tool = WebSearchTool(config=_MockConfig())
        assert isinstance(tool, Tool)

    def test_name_property(self):
        """name 应为 'web_search'。"""
        tool = WebSearchTool(config=_MockConfig())
        assert tool.name == "web_search"
        assert isinstance(tool.name, str)

    def test_description_property(self):
        """description 应为非空字符串。"""
        tool = WebSearchTool(config=_MockConfig())
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_parameters_schema_property(self):
        """parameters_schema 应定义 query（必填 string）和 max_results（可选 integer）。"""
        tool = WebSearchTool(config=_MockConfig())
        schema = tool.parameters_schema
        assert isinstance(schema, dict)
        assert schema["type"] == "object"
        # query: required string
        assert "query" in schema["properties"]
        assert schema["properties"]["query"]["type"] == "string"
        assert "query" in schema["required"]
        # max_results: optional integer with default/min/max
        assert "max_results" in schema["properties"]
        mr = schema["properties"]["max_results"]
        assert mr["type"] == "integer"
        assert mr["default"] == 10
        assert mr["minimum"] == 1
        assert mr["maximum"] == 20

    def test_category_is_browser(self):
        """category 应为 'browser'。"""
        tool = WebSearchTool(config=_MockConfig())
        assert tool.category == "browser"

    def test_is_concurrency_safe(self):
        """is_concurrency_safe 应为 True。"""
        tool = WebSearchTool(config=_MockConfig())
        assert tool.is_concurrency_safe is True

    def test_execute_is_callable(self):
        """execute 方法应存在且可调用。"""
        tool = WebSearchTool(config=_MockConfig())
        assert callable(tool.execute)


# ---------------------------------------------------------------------------
# Tests: API Key 未配置 (Requirement 2.5)
# ---------------------------------------------------------------------------


class TestAPIKeyNotConfigured:
    """验证 API Key 未配置时返回正确的错误信息。"""

    def test_empty_api_key_returns_error(self):
        """API Key 为空字符串时应返回 success=False。"""
        tool = WebSearchTool(config=_MockConfig(api_key=""))
        result = _run_async(tool.execute({"query": "test"}, context=None))

        assert result["success"] is False
        assert "API Key" in result["error"]
        assert "web_search_api_key" in result["error"]

    def test_no_config_returns_error(self):
        """未传入 config 时 API Key 默认为空，应返回错误。"""
        tool = WebSearchTool()
        result = _run_async(tool.execute({"query": "test"}, context=None))

        assert result["success"] is False
        assert "API Key" in result["error"]

    def test_api_key_error_has_metadata(self):
        """API Key 未配置的错误响应应包含 metadata。"""
        tool = WebSearchTool(config=_MockConfig(api_key=""))
        result = _run_async(tool.execute({"query": "test query"}, context=None))

        assert "metadata" in result
        assert result["metadata"]["query"] == "test query"
        assert result["metadata"]["result_count"] == 0


# ---------------------------------------------------------------------------
# Tests: 搜索 API 错误处理 (Requirement 2.5)
# ---------------------------------------------------------------------------


class TestSearchAPIErrorHandling:
    """验证搜索 API 返回错误时的处理。"""

    def test_api_403_forbidden(self):
        """API 返回 403 应返回 success=False 和包含状态码的错误信息。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="Forbidden")

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig())
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "403" in result["error"]

    def test_api_500_server_error(self):
        """API 返回 500 应返回 success=False 和包含状态码的错误信息。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig())
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "500" in result["error"]

    def test_api_429_rate_limit(self):
        """API 返回 429 应返回 success=False 和包含状态码的错误信息。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="Too Many Requests")

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig())
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "429" in result["error"]

    def test_api_timeout(self):
        """API 请求超时应返回 success=False 和超时错误信息。"""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("Connection timed out")

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig())
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "超时" in result["error"]

    def test_timeout_error_contains_query(self):
        """超时错误信息应包含搜索关键词。"""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig())
        result = _run_async(
            _execute_with_mock(tool, transport, params={"query": "Python 面试题"})
        )

        assert result["success"] is False
        assert "Python 面试题" in result["error"]

    def test_error_response_has_metadata(self):
        """错误响应应包含 metadata 字段。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="Bad Gateway")

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig())
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "metadata" in result
        assert "query" in result["metadata"]
        assert "result_count" in result["metadata"]
        assert "duration_ms" in result["metadata"]


# ---------------------------------------------------------------------------
# Tests: Mock 搜索 API 成功响应
# ---------------------------------------------------------------------------


class TestSearchAPISuccess:
    """验证搜索 API 成功响应时的处理。"""

    def test_successful_search_returns_results(self):
        """成功搜索应返回 success=True 和 results 列表。"""
        body = _make_bing_response()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig())
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is True
        assert isinstance(result["results"], list)
        assert len(result["results"]) == 2

    def test_result_structure(self):
        """每个搜索结果应包含 title、url、snippet 字段。"""
        body = _make_bing_response()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig())
        result = _run_async(_execute_with_mock(tool, transport))

        for item in result["results"]:
            assert "title" in item
            assert "url" in item
            assert "snippet" in item

    def test_success_metadata(self):
        """成功响应应包含正确的 metadata。"""
        body = _make_bing_response()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig())
        result = _run_async(
            _execute_with_mock(tool, transport, params={"query": "test query"})
        )

        assert result["metadata"]["query"] == "test query"
        assert result["metadata"]["result_count"] == 2
        assert result["metadata"]["duration_ms"] >= 0

    def test_api_sends_correct_headers(self):
        """API 请求应包含正确的 Ocp-Apim-Subscription-Key header。"""
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json=_make_bing_response())

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig(api_key="my-secret-key"))
        _run_async(_execute_with_mock(tool, transport))

        assert captured_headers.get("ocp-apim-subscription-key") == "my-secret-key"

    def test_empty_results_from_api(self):
        """API 返回空结果时应返回空列表。"""
        body = {"webPages": {"value": []}}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig())
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is True
        assert result["results"] == []
        assert result["metadata"]["result_count"] == 0

    def test_malformed_json_response(self):
        """API 返回非法 JSON 时应返回错误。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json", headers={"content-type": "text/plain"})

        transport = httpx.MockTransport(handler)
        tool = WebSearchTool(config=_MockConfig())
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "格式异常" in result["error"]
