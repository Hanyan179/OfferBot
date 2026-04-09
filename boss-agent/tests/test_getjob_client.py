"""
GetjobClient 单元测试

使用 httpx.MockTransport 模拟 HTTP 响应。
"""

from __future__ import annotations

import json

import httpx
import pytest

from services.getjob_client import GetjobClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_transport(handler):
    """创建 MockTransport 并注入到 GetjobClient。"""
    client = GetjobClient(base_url="http://test:8888")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test:8888",
        timeout=httpx.Timeout(5.0),
    )
    return client


def _ok_handler(request: httpx.Request) -> httpx.Response:
    """返回 200 + JSON body。"""
    return httpx.Response(200, json={"success": True, "message": "ok"})


def _error_handler(status: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="error body")
    return handler


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check_ok():
    client = _mock_transport(_ok_handler)
    result = await client.health_check()
    assert result["success"] is True
    assert result["data"]["success"] is True


@pytest.mark.asyncio
async def test_get_status():
    def handler(request: httpx.Request):
        assert "/api/liepin/status" in str(request.url)
        return httpx.Response(200, json={"isRunning": False, "isLoggedIn": True})
    client = _mock_transport(handler)
    result = await client.get_status("liepin")
    assert result["success"] is True
    assert result["data"]["isLoggedIn"] is True


@pytest.mark.asyncio
async def test_start_task():
    def handler(request: httpx.Request):
        assert request.method == "POST"
        assert "/api/zhilian/start" in str(request.url)
        return httpx.Response(200, json={"success": True, "status": "started"})
    client = _mock_transport(handler)
    result = await client.start_task("zhilian")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_stop_task():
    def handler(request: httpx.Request):
        assert "/api/liepin/stop" in str(request.url)
        return httpx.Response(200, json={"success": True})
    client = _mock_transport(handler)
    result = await client.stop_task("liepin")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_get_config():
    def handler(request: httpx.Request):
        assert "/api/liepin/config" in str(request.url)
        return httpx.Response(200, json={"config": {"keywords": "Java", "scrapeOnly": False}})
    client = _mock_transport(handler)
    result = await client.get_config("liepin")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_update_config():
    def handler(request: httpx.Request):
        assert request.method == "PUT"
        body = json.loads(request.content)
        assert body["scrapeOnly"] is True
        return httpx.Response(200, json={"id": 1, "scrapeOnly": True})
    client = _mock_transport(handler)
    result = await client.update_config("liepin", {"scrapeOnly": True})
    assert result["success"] is True


@pytest.mark.asyncio
async def test_get_job_list_with_filters():
    def handler(request: httpx.Request):
        assert "/api/zhilian/list" in str(request.url)
        assert "page=2" in str(request.url)
        assert "size=10" in str(request.url)
        return httpx.Response(200, json={"items": [], "total": 0})
    client = _mock_transport(handler)
    result = await client.get_job_list("zhilian", page=2, size=10)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_get_stats():
    def handler(request: httpx.Request):
        assert "/api/liepin/stats" in str(request.url)
        return httpx.Response(200, json={"kpi": {}, "charts": {}})
    client = _mock_transport(handler)
    result = await client.get_stats("liepin", keyword="AI")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_http_4xx_error():
    client = _mock_transport(_error_handler(404))
    result = await client.health_check()
    assert result["success"] is False
    assert "HTTP 404" in result["error"]


@pytest.mark.asyncio
async def test_http_5xx_error():
    client = _mock_transport(_error_handler(500))
    result = await client.health_check()
    assert result["success"] is False
    assert "内部错误" in result["error"]


@pytest.mark.asyncio
async def test_connection_refused():
    """连接拒绝时返回 success=False 且包含标记。"""
    # Use a port that is very unlikely to have anything listening
    client = GetjobClient(base_url="http://127.0.0.1:1")
    result = await client.health_check()
    assert result["success"] is False
    assert result["error"] is not None and len(result["error"]) > 0
    await client.close()


@pytest.mark.asyncio
async def test_platform_routing():
    """验证 platform 参数正确路由到 /api/{platform}/ 路径。"""
    paths_seen = []

    def handler(request: httpx.Request):
        paths_seen.append(str(request.url.path))
        return httpx.Response(200, json={"ok": True})

    client = _mock_transport(handler)
    await client.get_status("liepin")
    await client.get_status("zhilian")
    assert "/api/liepin/status" in paths_seen[0]
    assert "/api/zhilian/status" in paths_seen[1]
