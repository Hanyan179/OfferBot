"""
测试 POST /api/test/chat 测试接口

验证接口返回格式正确、tool_calls 结构完整、错误处理正常。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.app import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _mock_genai_response(text=None, function_calls=None):
    """创建模拟的 google-genai response。"""
    parts = []
    if function_calls:
        for fc in function_calls:
            part = MagicMock()
            part.text = None
            part.function_call = MagicMock()
            part.function_call.name = fc["name"]
            part.function_call.args = fc.get("args", {})
            part.function_call.id = fc.get("id", "test-id-1")
            parts.append(part)
    if text:
        part = MagicMock()
        part.text = text
        part.function_call = None
        parts.append(part)
    if not parts:
        part = MagicMock()
        part.text = ""
        part.function_call = None
        parts.append(part)

    candidate = MagicMock()
    candidate.content.parts = parts
    response = MagicMock()
    response.candidates = [candidate]
    return response


class TestChatApiValidation:
    """请求参数验证测试。"""

    @pytest.mark.anyio
    async def test_empty_body_returns_400(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/test/chat", json={})
            assert resp.status_code == 400
            assert resp.json()["ok"] is False

    @pytest.mark.anyio
    async def test_blank_message_returns_400(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/test/chat", json={"message": "   "})
            assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_invalid_json_returns_400(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/test/chat",
                content=b"not json",
                headers={"content-type": "application/json"},
            )
            assert resp.status_code == 400


class TestChatApiDisabled:
    @pytest.mark.anyio
    async def test_disabled_returns_403(self):
        with patch("web.app.load_config") as mock_cfg:
            cfg = MagicMock()
            cfg.enable_test_api = False
            mock_cfg.return_value = cfg
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/test/chat", json={"message": "hello"})
                assert resp.status_code == 403


class TestChatApiNoApiKey:
    @pytest.mark.anyio
    async def test_no_api_key_returns_400(self):
        with patch("web.app.load_config") as mock_cfg, \
             patch("web.app._get_db") as mock_db, \
             patch("web.app._load_llm_settings") as mock_llm:
            cfg = MagicMock()
            cfg.enable_test_api = True
            mock_cfg.return_value = cfg
            mock_db.return_value = MagicMock()
            mock_llm.return_value = {"llm_api_key": ""}

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/test/chat", json={"message": "hello"})
                assert resp.status_code == 400
                assert "API Key" in resp.json()["error"]


class TestChatApiResponseFormat:
    """验证正常响应的格式（mock google-genai SDK）。"""

    def _setup_mocks(self, mock_cfg, mock_db, mock_llm, mock_registry, mock_genai, genai_responses):
        """通用 mock 设置。"""
        cfg = MagicMock()
        cfg.enable_test_api = True
        mock_cfg.return_value = cfg
        mock_db.return_value = MagicMock()
        mock_llm.return_value = {"llm_api_key": "test-key"}

        # mock registry
        from agent.tool_registry import ToolRegistry
        registry = ToolRegistry()
        mock_registry.return_value = (registry, MagicMock())

        # mock genai client
        mock_client_instance = MagicMock()
        call_count = [0]
        def side_effect(*args, **kwargs):
            idx = min(call_count[0], len(genai_responses) - 1)
            call_count[0] += 1
            return genai_responses[idx]
        mock_client_instance.models.generate_content = side_effect
        mock_genai.return_value = mock_client_instance

    @pytest.mark.anyio
    async def test_simple_text_reply(self):
        """模拟纯文本回复。"""
        with patch("web.app.load_config") as mock_cfg, \
             patch("web.app._get_db") as mock_db, \
             patch("web.app._load_llm_settings") as mock_llm, \
             patch("agent.bootstrap.create_tool_registry") as mock_registry, \
             patch("google.genai.Client") as mock_genai:
            self._setup_mocks(mock_cfg, mock_db, mock_llm, mock_registry, mock_genai, [
                _mock_genai_response(text="你好，有什么可以帮你的？"),
            ])

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/test/chat", json={"message": "你好"})
                assert resp.status_code == 200
                data = resp.json()
                assert data["ok"] is True
                assert data["reply"] == "你好，有什么可以帮你的？"
                assert isinstance(data["tool_calls"], list)
                assert len(data["tool_calls"]) == 0
                assert "total_duration_ms" in data
                assert "model" in data

    @pytest.mark.anyio
    async def test_tool_call_and_reply(self):
        """模拟 tool 调用 + 最终回复。"""
        from agent.tool_registry import Tool, ToolRegistry

        class MockTool(Tool):
            @property
            def name(self): return "get_stats"
            @property
            def description(self): return "获取统计"
            @property
            def parameters_schema(self): return {"type": "object", "properties": {}}
            async def execute(self, params, context):
                return {"total": 10}

        with patch("web.app.load_config") as mock_cfg, \
             patch("web.app._get_db") as mock_db, \
             patch("web.app._load_llm_settings") as mock_llm, \
             patch("agent.bootstrap.create_tool_registry") as mock_registry, \
             patch("google.genai.Client") as mock_genai:

            registry = ToolRegistry()
            registry.register(MockTool())
            mock_registry.return_value = (registry, MagicMock())

            cfg = MagicMock()
            cfg.enable_test_api = True
            mock_cfg.return_value = cfg
            mock_db.return_value = MagicMock()
            mock_llm.return_value = {"llm_api_key": "test-key"}

            # 第一次调用返回 function call，第二次返回文本
            mock_client_instance = MagicMock()
            responses = [
                _mock_genai_response(function_calls=[{"name": "get_stats", "args": {}, "id": "fc1"}]),
                _mock_genai_response(text="你有 10 条投递记录"),
            ]
            call_count = [0]
            def side_effect(*args, **kwargs):
                idx = min(call_count[0], len(responses) - 1)
                call_count[0] += 1
                return responses[idx]
            mock_client_instance.models.generate_content = side_effect
            mock_genai.return_value = mock_client_instance

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/test/chat", json={"message": "查看统计"})
                data = resp.json()
                assert data["ok"] is True
                assert data["reply"] == "你有 10 条投递记录"
                assert len(data["tool_calls"]) == 1
                tc = data["tool_calls"][0]
                assert tc["name"] == "get_stats"
                assert tc["success"] is True
                assert "duration_ms" in tc

    @pytest.mark.anyio
    async def test_tool_not_found(self):
        """调用不存在的 tool。"""
        with patch("web.app.load_config") as mock_cfg, \
             patch("web.app._get_db") as mock_db, \
             patch("web.app._load_llm_settings") as mock_llm, \
             patch("agent.bootstrap.create_tool_registry") as mock_registry, \
             patch("google.genai.Client") as mock_genai:

            from agent.tool_registry import ToolRegistry
            registry = ToolRegistry()
            mock_registry.return_value = (registry, MagicMock())

            cfg = MagicMock()
            cfg.enable_test_api = True
            mock_cfg.return_value = cfg
            mock_db.return_value = MagicMock()
            mock_llm.return_value = {"llm_api_key": "test-key"}

            mock_client_instance = MagicMock()
            responses = [
                _mock_genai_response(function_calls=[{"name": "nonexistent_tool", "args": {}, "id": "fc1"}]),
                _mock_genai_response(text="抱歉，工具不可用"),
            ]
            call_count = [0]
            def side_effect(*args, **kwargs):
                idx = min(call_count[0], len(responses) - 1)
                call_count[0] += 1
                return responses[idx]
            mock_client_instance.models.generate_content = side_effect
            mock_genai.return_value = mock_client_instance

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/test/chat", json={"message": "test"})
                data = resp.json()
                assert data["ok"] is True
                assert len(data["tool_calls"]) == 1
                tc = data["tool_calls"][0]
                assert tc["success"] is False
                assert "not found" in tc["result"]
