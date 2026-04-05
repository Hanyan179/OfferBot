"""
对话管理器 — 封装对话的创建、列表、切换、删除逻辑。

在现有 ChatHistoryStore（JSONL 文件存储）基础上，提供对话生命周期管理的
业务逻辑层。

需求: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 4.1
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.data.chat_history import ChatHistoryStore

logger = logging.getLogger(__name__)


class ConversationManager:
    """对话管理器 — 封装对话的创建、列表、切换、删除逻辑。"""

    def __init__(self, store: ChatHistoryStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # 创建新对话
    # ------------------------------------------------------------------

    async def create_conversation(self) -> dict[str, Any]:
        """创建新对话，返回 {id, created_at, summary}。"""
        conversation_id = await self._store.create_conversation()
        created_at = self._id_to_datetime_str(conversation_id)
        return {
            "id": conversation_id,
            "created_at": created_at,
            "summary": "",
        }

    # ------------------------------------------------------------------
    # 对话列表
    # ------------------------------------------------------------------

    async def list_conversations(self) -> list[dict[str, Any]]:
        """列出所有对话，按创建时间倒序。"""
        base_dir: Path = self._store.base_dir
        if not base_dir.exists():
            return []

        active_id = await self._store.get_active_conversation_id()
        conversations: list[dict[str, Any]] = []

        for filepath in sorted(base_dir.glob("*.jsonl"), reverse=True):
            conv_id = filepath.stem
            messages = await self._store.load_history(conv_id, limit=None)
            summary = self._extract_summary(messages)
            conversations.append({
                "id": conv_id,
                "created_at": self._id_to_datetime_str(conv_id),
                "summary": summary,
                "message_count": len(messages),
                "is_active": conv_id == active_id,
            })

        return conversations

    # ------------------------------------------------------------------
    # 获取对话消息
    # ------------------------------------------------------------------

    async def get_conversation_messages(
        self, conversation_id: str
    ) -> list[dict[str, Any]]:
        """加载指定对话的完整消息历史。"""
        return await self._store.load_history(conversation_id, limit=None)

    # ------------------------------------------------------------------
    # 删除对话
    # ------------------------------------------------------------------

    async def delete_conversation(self, conversation_id: str) -> bool:
        """删除对话文件，返回是否成功。"""
        filepath = self._store._conversation_path(conversation_id)
        try:
            if filepath.exists():
                filepath.unlink()
            return True
        except OSError:
            logger.exception("删除对话文件失败: %s", conversation_id)
            return False

    # ------------------------------------------------------------------
    # 对话摘要
    # ------------------------------------------------------------------

    async def get_conversation_summary(self, conversation_id: str) -> str:
        """提取对话摘要：首条 user 消息的前 50 个字符。"""
        messages = await self._store.load_history(conversation_id, limit=None)
        return self._extract_summary(messages)

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_summary(messages: list[dict[str, Any]]) -> str:
        """从消息列表中提取摘要：首条 user 消息 content 的前 50 个字符。"""
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                return content[:50]
        return ""

    @staticmethod
    def _id_to_datetime_str(conversation_id: str) -> str:
        """将会话 ID（时间戳格式）转换为可读日期时间字符串。"""
        try:
            dt = datetime.strptime(conversation_id, "%Y-%m-%dT%H-%M-%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return conversation_id
