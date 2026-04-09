"""
测试对话管理 REST API 路由

验证 GET/POST/DELETE /api/conversations 端点的功能和错误处理。
使用 httpx + pytest-asyncio 测试，tmp_path 隔离数据。

需求: 1.1, 2.1, 3.1, 4.1
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.app import app


@pytest.fixture(autouse=True)
def _isolate_conversation_manager(tmp_path):
    """每个测试使用独立的 tmp_path，避免数据污染。"""
    from agent.conversation_manager import ConversationManager
    from tools.data.chat_history import ChatHistoryStore

    store = ChatHistoryStore(base_dir=str(tmp_path / "conversations"))
    mgr = ConversationManager(store)

    # 直接注入到 app.state
    app.state.conversation_manager = mgr
    yield mgr
    # 清理
    app.state.conversation_manager = None


class TestListConversations:
    """GET /api/conversations"""

    @pytest.mark.anyio
    async def test_empty_list(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/conversations")
            assert resp.status_code == 200
            data = resp.json()
            assert data["conversations"] == []

    @pytest.mark.anyio
    async def test_list_after_create(self, _isolate_conversation_manager):
        mgr = _isolate_conversation_manager
        await mgr.create_conversation()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/conversations")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["conversations"]) == 1
            conv = data["conversations"][0]
            assert "id" in conv
            assert "created_at" in conv
            assert "summary" in conv
            assert "message_count" in conv
            assert "is_active" in conv


class TestCreateConversation:
    """POST /api/conversations"""

    @pytest.mark.anyio
    async def test_create_returns_conversation(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/conversations")
            assert resp.status_code == 200
            data = resp.json()
            assert "id" in data
            assert "created_at" in data
            assert "summary" in data

    @pytest.mark.anyio
    async def test_create_appears_in_list(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            create_resp = await client.post("/api/conversations")
            conv_id = create_resp.json()["id"]

            list_resp = await client.get("/api/conversations")
            ids = [c["id"] for c in list_resp.json()["conversations"]]
            assert conv_id in ids


class TestGetConversationMessages:
    """GET /api/conversations/{id}/messages"""

    @pytest.mark.anyio
    async def test_empty_conversation(self, _isolate_conversation_manager):
        mgr = _isolate_conversation_manager
        conv = await mgr.create_conversation()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/conversations/{conv['id']}/messages")
            assert resp.status_code == 200
            data = resp.json()
            assert data["messages"] == []

    @pytest.mark.anyio
    async def test_conversation_with_messages(self, _isolate_conversation_manager):
        mgr = _isolate_conversation_manager
        conv = await mgr.create_conversation()
        await mgr._store.save_message(conv["id"], "user", "你好")
        await mgr._store.save_message(conv["id"], "assistant", "你好！有什么可以帮你的？")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/conversations/{conv['id']}/messages")
            assert resp.status_code == 200
            messages = resp.json()["messages"]
            assert len(messages) == 2
            assert messages[0]["role"] == "user"
            assert messages[0]["content"] == "你好"
            assert messages[1]["role"] == "assistant"

    @pytest.mark.anyio
    async def test_nonexistent_conversation(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/conversations/nonexistent-id/messages")
            assert resp.status_code == 200
            data = resp.json()
            assert data["messages"] == []


class TestDeleteConversation:
    """DELETE /api/conversations/{id}"""

    @pytest.mark.anyio
    async def test_delete_conversation(self, _isolate_conversation_manager):
        """删除非活跃对话。"""
        mgr = _isolate_conversation_manager
        # 创建一个旧对话（非活跃）
        old_id = "2025-01-01T00-00-00"
        mgr._store._ensure_dir()
        (mgr._store.base_dir / f"{old_id}.jsonl").touch()
        # 创建一个新对话（活跃 = 最新的）
        new_conv = await mgr.create_conversation()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 删除旧的非活跃对话
            resp = await client.delete(f"/api/conversations/{old_id}")
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

            # 验证已从列表中移除
            list_resp = await client.get("/api/conversations")
            ids = [c["id"] for c in list_resp.json()["conversations"]]
            assert old_id not in ids
            # 活跃对话仍在
            assert new_conv["id"] in ids

    @pytest.mark.anyio
    async def test_delete_active_conversation_creates_new(self, _isolate_conversation_manager):
        """删除活跃对话时，应先创建新对话再删除。"""
        mgr = _isolate_conversation_manager
        # 手动创建一个带旧时间戳的对话文件，确保新对话 ID 不同
        old_id = "2025-01-01T00-00-00"
        filepath = mgr._store.base_dir / f"{old_id}.jsonl"
        mgr._store._ensure_dir()
        filepath.touch()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 确认旧对话是活跃的（最新的 .jsonl）
            list_resp = await client.get("/api/conversations")
            conversations = list_resp.json()["conversations"]
            assert len(conversations) == 1
            assert conversations[0]["id"] == old_id

            resp = await client.delete(f"/api/conversations/{old_id}")
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

            # 列表中应有新创建的对话，但不包含被删除的
            list_resp = await client.get("/api/conversations")
            conversations = list_resp.json()["conversations"]
            ids = [c["id"] for c in conversations]
            assert old_id not in ids
            # 删除活跃对话后应自动创建了新对话
            assert len(conversations) >= 1

    @pytest.mark.anyio
    async def test_delete_nonexistent_conversation(self):
        """删除不存在的对话应静默成功（幂等）。"""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api/conversations/nonexistent-id")
            assert resp.status_code == 200
            assert resp.json()["ok"] is True
