"""
对话历史持久化模块 — 基于 JSONL 文件

参考 Claude Code history.ts 架构，每个会话一个独立 .jsonl 文件，
文件名为时间戳格式的会话 ID。支持消息追加、历史加载、会话恢复。

本项目为个人本地自用，不存在多用户/多并发场景。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONVERSATIONS_DIR = "boss-agent/data/conversations"


class ChatHistoryStore:
    """
    对话历史持久化。JSONL 文件存储。
    每个会话一个 .jsonl 文件，文件名为会话 ID（时间戳格式）。
    """

    MAX_RESTORE_MESSAGES = 200

    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = Path(base_dir or CONVERSATIONS_DIR)

    def _ensure_dir(self) -> None:
        """确保对话历史文件夹存在。"""
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _conversation_path(self, conversation_id: str) -> Path:
        """获取会话 JSONL 文件路径。"""
        return self.base_dir / f"{conversation_id}.jsonl"

    async def create_conversation(self) -> str:
        """创建新会话，返回时间戳格式的会话 ID，创建对应 .jsonl 文件。"""
        self._ensure_dir()
        conversation_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        filepath = self._conversation_path(conversation_id)
        filepath.touch(exist_ok=True)
        return conversation_id

    async def get_active_conversation_id(self) -> str | None:
        """扫描文件夹，返回最新的 .jsonl 文件名（去掉扩展名）。"""
        if not self.base_dir.exists():
            return None
        jsonl_files = sorted(self.base_dir.glob("*.jsonl"))
        if not jsonl_files:
            return None
        return jsonl_files[-1].stem

    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """追加一行 JSON 到会话的 .jsonl 文件。"""
        self._ensure_dir()
        filepath = self._conversation_path(conversation_id)
        record: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if metadata:
            record["metadata"] = metadata
        with filepath.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def load_history(
        self,
        conversation_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        读取 .jsonl 文件返回消息列表。

        如果 limit 未指定，默认使用 MAX_RESTORE_MESSAGES。
        返回最近的 limit 条消息（保持时间顺序）。
        """
        filepath = self._conversation_path(conversation_id)
        if not filepath.exists():
            return []

        effective_limit = limit if limit is not None else self.MAX_RESTORE_MESSAGES
        messages: list[dict[str, Any]] = []

        with filepath.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("跳过无法解析的 JSONL 行: %s", line[:80])

        # 超过限制时只返回最近的消息
        if len(messages) > effective_limit:
            messages = messages[-effective_limit:]

        return messages
