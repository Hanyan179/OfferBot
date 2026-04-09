"""
WebFetchTool 单元测试

测试 HTTP 错误码处理、请求超时处理、Tool ABC 接口合规。
使用 httpx.MockTransport mock HTTP 请求。

需求: 1.5, 1.6, 3.1, 3.3, 3.4, 3.6
"""

from __future__ import annotations

import asyncio

import httpx

from agent.tool_registry import Tool
from tools.browser.web_fetch import TTLCache, WebFetchTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_tool_with_transport(transport: httpx.MockTransport) -> WebFetchTool:
    """Create a WebFetchTool with a fresh cache and patched transport."""
    tool = WebFetchTool()
    tool._cache = TTLCache(ttl_seconds=0)  # disable cache
    tool._transport = transport  # store for patching
    return tool


async def _execute_with_mock(
    tool: WebFetchTool,
    transport: httpx.MockTransport,
    url: str = "https://example.com",
) -> dict:
    """Execute tool with monkey-patched AsyncClient to use mock transport."""
    original_init = httpx.AsyncClient.__init__

    def patched_init(self_client, **kwargs):
        kwargs["transport"] = transport
        original_init(self_client, **kwargs)

    httpx.AsyncClient.__init__ = patched_init
    try:
        return await tool.execute({"url": url}, context=None)
    finally:
        httpx.AsyncClient.__init__ = original_init


# ---------------------------------------------------------------------------
# Tests: Tool ABC 接口合规 (Requirements 3.1, 3.3, 3.4, 3.6)
# ---------------------------------------------------------------------------


class TestWebFetchToolABCCompliance:
    """验证 WebFetchTool 正确实现 Tool ABC 接口。"""

    def test_inherits_from_tool(self):
        """WebFetchTool 应继承 Tool ABC。"""
        tool = WebFetchTool()
        assert isinstance(tool, Tool)

    def test_name_property(self):
        """name 应为 'web_fetch'。"""
        tool = WebFetchTool()
        assert tool.name == "web_fetch"
        assert isinstance(tool.name, str)

    def test_description_property(self):
        """description 应为非空字符串。"""
        tool = WebFetchTool()
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0

    def test_parameters_schema_property(self):
        """parameters_schema 应定义 url 为必填 string 参数。"""
        tool = WebFetchTool()
        schema = tool.parameters_schema
        assert isinstance(schema, dict)
        assert schema["type"] == "object"
        assert "url" in schema["properties"]
        assert schema["properties"]["url"]["type"] == "string"
        assert "url" in schema["required"]

    def test_category_is_browser(self):
        """category 应为 'browser'。"""
        tool = WebFetchTool()
        assert tool.category == "browser"

    def test_is_concurrency_safe(self):
        """is_concurrency_safe 应为 True。"""
        tool = WebFetchTool()
        assert tool.is_concurrency_safe is True

    def test_execute_is_callable(self):
        """execute 方法应存在且可调用。"""
        tool = WebFetchTool()
        assert callable(tool.execute)


# ---------------------------------------------------------------------------
# Tests: HTTP 错误码处理 (Requirement 1.5)
# ---------------------------------------------------------------------------


class TestHTTPErrorHandling:
    """验证非 2xx 状态码返回正确的错误信息。"""

    def test_404_not_found(self):
        """404 应返回 success=False 和包含状态码的错误信息。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        tool = _make_tool_with_transport(transport)
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "404" in result["error"]
        assert result["metadata"]["status_code"] == 404

    def test_500_internal_server_error(self):
        """500 应返回 success=False 和包含状态码的错误信息。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        transport = httpx.MockTransport(handler)
        tool = _make_tool_with_transport(transport)
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "500" in result["error"]
        assert result["metadata"]["status_code"] == 500

    def test_403_forbidden(self):
        """403 应返回 success=False 和包含状态码的错误信息。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        transport = httpx.MockTransport(handler)
        tool = _make_tool_with_transport(transport)
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "403" in result["error"]
        assert result["metadata"]["status_code"] == 403

    def test_error_response_has_metadata(self):
        """错误响应应包含 metadata 字段。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502)

        transport = httpx.MockTransport(handler)
        tool = _make_tool_with_transport(transport)
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "metadata" in result
        assert "status_code" in result["metadata"]
        assert "duration_ms" in result["metadata"]
        assert "final_url" in result["metadata"]

    def test_error_message_format(self):
        """错误信息应包含 'HTTP {status_code}' 格式。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        tool = _make_tool_with_transport(transport)
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["error"].startswith("HTTP 404")


# ---------------------------------------------------------------------------
# Tests: 请求超时处理 (Requirement 1.6)
# ---------------------------------------------------------------------------


class TestTimeoutHandling:
    """验证请求超时返回正确的错误信息。"""

    def test_timeout_returns_error(self):
        """超时应返回 success=False 和超时错误信息。"""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("Connection timed out")

        transport = httpx.MockTransport(handler)
        tool = _make_tool_with_transport(transport)
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "超时" in result["error"]

    def test_timeout_error_contains_url(self):
        """超时错误信息应包含请求的 URL。"""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        transport = httpx.MockTransport(handler)
        tool = _make_tool_with_transport(transport)
        url = "https://slow-site.example.com/page"
        result = _run_async(_execute_with_mock(tool, transport, url=url))

        assert result["success"] is False
        assert url in result["error"]

    def test_timeout_error_contains_timeout_value(self):
        """超时错误信息应包含超时秒数。"""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        transport = httpx.MockTransport(handler)
        tool = _make_tool_with_transport(transport)
        result = _run_async(_execute_with_mock(tool, transport))

        assert result["success"] is False
        assert "30s" in result["error"]  # default timeout

    def test_timeout_has_metadata(self):
        """超时响应应包含 metadata。"""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        transport = httpx.MockTransport(handler)
        tool = _make_tool_with_transport(transport)
        result = _run_async(_execute_with_mock(tool, transport))

        assert "metadata" in result
        assert "duration_ms" in result["metadata"]
        assert "final_url" in result["metadata"]
