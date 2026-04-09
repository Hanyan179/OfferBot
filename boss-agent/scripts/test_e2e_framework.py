"""
框架核心修复 — 端到端测试脚本

验证对话管理 API、Tool 中文显示名、对话切换与历史恢复、边界场景等。
使用 httpx.AsyncClient + FastAPI app（进程内测试，无需启动真实服务器）。

用法:
    cd boss-agent
    pytest scripts/test_e2e_framework.py -v
    # 或直接运行
    python scripts/test_e2e_framework.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# 确保 boss-agent 目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.conversation_manager import ConversationManager
from tools.data.chat_history import ChatHistoryStore
from web.app import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate_data(tmp_path):
    """每个测试使用独立的 tmp_path，注入隔离的 ConversationManager。"""
    store = ChatHistoryStore(base_dir=str(tmp_path / "conversations"))
    mgr = ConversationManager(store)
    app.state.conversation_manager = mgr
    yield mgr
    app.state.conversation_manager = None


def _client():
    """创建 httpx AsyncClient，复用同一 app 实例。"""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ===========================================================================
# Test 1: 对话管理 API 全流程
# ===========================================================================

class TestConversationAPIFullFlow:
    """对话管理 API 全流程 — 创建、列表、保存消息、加载消息、切换、删除。"""

    @pytest.mark.anyio
    async def test_full_conversation_lifecycle(self, _isolate_data):
        mgr = _isolate_data

        async with _client() as client:
            # ---- 1. 创建对话 ----
            resp = await client.post("/api/conversations")
            assert resp.status_code == 200
            conv = resp.json()
            assert "id" in conv, "创建对话应返回 id"
            assert "created_at" in conv, "创建对话应返回 created_at"
            assert "summary" in conv, "创建对话应返回 summary"
            conv_id = conv["id"]

            # ---- 2. 列表中应包含刚创建的对话 ----
            resp = await client.get("/api/conversations")
            assert resp.status_code == 200
            conversations = resp.json()["conversations"]
            ids = [c["id"] for c in conversations]
            assert conv_id in ids, "列表中应包含刚创建的对话"

            # ---- 3. 通过 ConversationManager 直接保存消息（无需 LLM） ----
            await mgr._store.save_message(conv_id, "user", "你好，帮我找工作")
            await mgr._store.save_message(conv_id, "assistant", "好的，请问你想找什么类型的工作？")

            # ---- 4. 通过 API 加载消息，验证一致性 ----
            resp = await client.get(f"/api/conversations/{conv_id}/messages")
            assert resp.status_code == 200
            messages = resp.json()["messages"]
            assert len(messages) == 2, "应有 2 条消息"
            assert messages[0]["role"] == "user"
            assert messages[0]["content"] == "你好，帮我找工作"
            assert messages[1]["role"] == "assistant"
            assert messages[1]["content"] == "好的，请问你想找什么类型的工作？"

            # ---- 5. 创建第二个对话（模拟切换） ----
            time.sleep(1)  # 确保时间戳不同
            resp2 = await client.post("/api/conversations")
            assert resp2.status_code == 200
            conv2_id = resp2.json()["id"]
            assert conv2_id != conv_id, "第二个对话 ID 应不同"

            # ---- 6. 删除第一个对话 ----
            resp = await client.delete(f"/api/conversations/{conv_id}")
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

            # 验证已从列表中移除
            resp = await client.get("/api/conversations")
            ids = [c["id"] for c in resp.json()["conversations"]]
            assert conv_id not in ids, "删除后不应出现在列表中"
            assert conv2_id in ids, "第二个对话应仍在列表中"


# ===========================================================================
# Test 2: Tool 中文显示名验证
# ===========================================================================

class TestToolDisplayNames:
    """Tool 中文显示名验证 — 在 registry 层面验证，不需要 LLM。"""

    def test_all_tools_have_display_name(self):
        """所有注册的 Tool 都应有非空 display_name。"""
        from agent.bootstrap import create_tool_registry

        registry, _skill_loader = create_tool_registry()
        tool_names = registry.list_tool_names()
        assert len(tool_names) > 0, "应至少有一个已注册的 Tool"

        for name in tool_names:
            tool = registry.get_tool(name)
            assert tool is not None, f"Tool '{name}' 应存在"
            assert tool.display_name, f"Tool '{name}' 的 display_name 不应为空"

    def test_get_display_name_returns_tool_display_name(self):
        """registry.get_display_name 应返回 tool.display_name。"""
        from agent.bootstrap import create_tool_registry

        registry, _skill_loader = create_tool_registry()
        tool_names = registry.list_tool_names()

        for name in tool_names:
            tool = registry.get_tool(name)
            result = registry.get_display_name(name)
            assert result == tool.display_name, (
                f"get_display_name('{name}') 应返回 '{tool.display_name}'，"
                f"实际返回 '{result}'"
            )

    def test_get_display_name_unknown_tool_returns_name(self):
        """对未知 tool_name，get_display_name 应回退返回 tool_name 本身。"""
        from agent.bootstrap import create_tool_registry

        registry, _skill_loader = create_tool_registry()
        unknown = "completely_unknown_tool_xyz"
        result = registry.get_display_name(unknown)
        assert result == unknown, "未知 tool 应回退返回 tool_name 本身"


# ===========================================================================
# Test 3: 模拟用户真实对话场景（无需 LLM）
# ===========================================================================

class TestSimulatedUserScenario:
    """模拟用户真实对话场景 — 创建对话、保存消息、验证持久化和摘要。"""

    @pytest.mark.anyio
    async def test_user_conversation_flow(self, _isolate_data):
        mgr = _isolate_data

        async with _client() as client:
            # ---- 创建对话 ----
            resp = await client.post("/api/conversations")
            conv_id = resp.json()["id"]

            # ---- 保存用户消息和助手回复 ----
            user_msg = "帮我搜索上海 AI 岗位"
            assistant_msg = "好的，我来帮你搜索上海的 AI 相关岗位，请稍等..."
            await mgr._store.save_message(conv_id, "user", user_msg)
            await mgr._store.save_message(conv_id, "assistant", assistant_msg)

            # ---- 通过 API 加载消息，验证持久化 ----
            resp = await client.get(f"/api/conversations/{conv_id}/messages")
            messages = resp.json()["messages"]
            assert len(messages) == 2, "应有 2 条消息"
            assert messages[0]["content"] == user_msg
            assert messages[1]["content"] == assistant_msg

            # ---- 列表中验证摘要 ----
            resp = await client.get("/api/conversations")
            conversations = resp.json()["conversations"]
            target = [c for c in conversations if c["id"] == conv_id]
            assert len(target) == 1, "应找到目标对话"
            # 摘要 = 首条 user 消息的前 50 字符
            assert target[0]["summary"] == user_msg[:50], (
                f"摘要应为 '{user_msg[:50]}'，实际为 '{target[0]['summary']}'"
            )

    def test_tool_display_names_are_chinese(self):
        """验证 Tool 显示名包含中文字符。"""
        import re

        from agent.bootstrap import create_tool_registry

        registry, _skill_loader = create_tool_registry()
        # 中文字符正则
        chinese_pattern = re.compile(r"[\u4e00-\u9fff]")

        tool_names = registry.list_tool_names()
        chinese_count = 0
        for name in tool_names:
            display = registry.get_display_name(name)
            if chinese_pattern.search(display):
                chinese_count += 1

        # 大部分 tool 应有中文显示名
        assert chinese_count > 0, "至少应有一个 Tool 具有中文显示名"
        ratio = chinese_count / len(tool_names)
        assert ratio > 0.5, (
            f"超过半数的 Tool 应有中文显示名，"
            f"当前 {chinese_count}/{len(tool_names)} ({ratio:.0%})"
        )


# ===========================================================================
# Test 4: 对话切换与历史恢复
# ===========================================================================

class TestConversationSwitchAndRestore:
    """对话切换与历史恢复 — 创建多个对话，验证各自消息隔离和列表排序。"""

    @pytest.mark.anyio
    async def test_multiple_conversations_isolation(self, _isolate_data):
        mgr = _isolate_data

        async with _client() as client:
            # ---- 创建 3 个对话，每个间隔 1 秒确保 ID 不同 ----
            conv_ids = []
            messages_map = {
                0: [("user", "第一个对话的消息"), ("assistant", "回复第一个")],
                1: [("user", "第二个对话的消息"), ("assistant", "回复第二个")],
                2: [("user", "第三个对话的消息"), ("assistant", "回复第三个")],
            }

            for i in range(3):
                if i > 0:
                    time.sleep(1)  # 确保时间戳唯一
                resp = await client.post("/api/conversations")
                assert resp.status_code == 200
                cid = resp.json()["id"]
                conv_ids.append(cid)

                # 保存该对话的消息
                for role, content in messages_map[i]:
                    await mgr._store.save_message(cid, role, content)

            # ---- 验证每个对话加载的消息正确 ----
            for i, cid in enumerate(conv_ids):
                resp = await client.get(f"/api/conversations/{cid}/messages")
                assert resp.status_code == 200
                msgs = resp.json()["messages"]
                assert len(msgs) == 2, f"对话 {i} 应有 2 条消息"
                assert msgs[0]["content"] == messages_map[i][0][1], (
                    f"对话 {i} 的第一条消息内容不匹配"
                )
                assert msgs[1]["content"] == messages_map[i][1][1], (
                    f"对话 {i} 的第二条消息内容不匹配"
                )

            # ---- 验证列表按创建时间倒序（最新在前） ----
            resp = await client.get("/api/conversations")
            conversations = resp.json()["conversations"]
            assert len(conversations) == 3, "应有 3 个对话"
            listed_ids = [c["id"] for c in conversations]
            # 最新创建的应排在最前面
            assert listed_ids[0] == conv_ids[2], "最新对话应排在第一位"
            assert listed_ids[-1] == conv_ids[0], "最早对话应排在最后"

            # ---- 删除中间的对话 ----
            mid_id = conv_ids[1]
            resp = await client.delete(f"/api/conversations/{mid_id}")
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

            # 验证只剩 2 个对话
            resp = await client.get("/api/conversations")
            conversations = resp.json()["conversations"]
            remaining_ids = [c["id"] for c in conversations]
            assert len(remaining_ids) == 2, "删除后应剩 2 个对话"
            assert mid_id not in remaining_ids, "被删除的对话不应在列表中"
            assert conv_ids[0] in remaining_ids, "第一个对话应仍在"
            assert conv_ids[2] in remaining_ids, "第三个对话应仍在"


# ===========================================================================
# Test 5: 边界场景
# ===========================================================================

class TestEdgeCases:
    """边界场景 — 空列表、删除活跃对话、损坏的 JSONL 文件。"""

    @pytest.mark.anyio
    async def test_empty_conversation_list(self, _isolate_data):
        """全新 tmp 目录下，对话列表应为空。"""
        async with _client() as client:
            resp = await client.get("/api/conversations")
            assert resp.status_code == 200
            assert resp.json()["conversations"] == [], "初始状态应为空列表"

    @pytest.mark.anyio
    async def test_delete_active_conversation_auto_creates_new(self, _isolate_data):
        """删除活跃对话后，应自动创建新对话。"""
        mgr = _isolate_data

        async with _client() as client:
            # 创建一个对话（使用旧时间戳确保新对话 ID 不同）
            old_id = "2025-01-01T00-00-00"
            mgr._store._ensure_dir()
            (mgr._store.base_dir / f"{old_id}.jsonl").touch()

            # 确认它是唯一的（也是活跃的）
            resp = await client.get("/api/conversations")
            conversations = resp.json()["conversations"]
            assert len(conversations) == 1
            assert conversations[0]["id"] == old_id

            # 删除活跃对话
            resp = await client.delete(f"/api/conversations/{old_id}")
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

            # 列表中应有新创建的对话，旧的已被删除
            resp = await client.get("/api/conversations")
            conversations = resp.json()["conversations"]
            ids = [c["id"] for c in conversations]
            assert old_id not in ids, "旧对话应已被删除"
            assert len(conversations) >= 1, "应自动创建了新对话"

    @pytest.mark.anyio
    async def test_corrupted_jsonl_file_handling(self, _isolate_data):
        """损坏的 JSONL 文件 — load_history 应跳过无法解析的行。"""
        mgr = _isolate_data

        # 手动创建一个包含损坏行的 JSONL 文件
        conv_id = "2025-06-01T12-00-00"
        mgr._store._ensure_dir()
        filepath = mgr._store.base_dir / f"{conv_id}.jsonl"

        lines = [
            json.dumps({"role": "user", "content": "正常消息1", "timestamp": "2025-06-01T12:00:01"}, ensure_ascii=False),
            "这不是有效的 JSON {{{",
            "",  # 空行
            json.dumps({"role": "assistant", "content": "正常消息2", "timestamp": "2025-06-01T12:00:02"}, ensure_ascii=False),
            '{"role": "user", "content": "正常消息3"',  # 截断的 JSON
            json.dumps({"role": "user", "content": "正常消息4", "timestamp": "2025-06-01T12:00:03"}, ensure_ascii=False),
        ]
        filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # 通过 API 加载消息
        async with _client() as client:
            resp = await client.get(f"/api/conversations/{conv_id}/messages")
            assert resp.status_code == 200
            messages = resp.json()["messages"]

            # 应只返回可解析的有效消息（跳过损坏行和空行）
            assert len(messages) == 3, (
                f"应有 3 条有效消息（跳过损坏行），实际 {len(messages)} 条"
            )
            assert messages[0]["content"] == "正常消息1"
            assert messages[1]["content"] == "正常消息2"
            assert messages[2]["content"] == "正常消息4"


# ---------------------------------------------------------------------------
# 独立运行入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
