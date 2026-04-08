"""
执行轨迹持久化模块 — AI 执行步骤调试器

记录每次对话中 Agent 的完整执行轨迹：
thinking → tool_start → tool_result → assistant_message → error

每个会话一个 .trace.jsonl 文件，与 ChatHistoryStore 的对话文件一一对应。
用于事后分析 AI 在哪一步出了问题。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_BASE = Path(__file__).resolve().parent.parent / "data" / "traces"


class ExecutionTraceStore:
    """
    执行轨迹持久化。每次用户消息触发的完整 Agent 执行流程记录为一个 trace entry。

    文件结构：
        data/traces/{conversation_id}.trace.jsonl
    """

    base_dir: str | None

    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else _DEFAULT_BASE

    def _ensure_dir(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _trace_path(self, conversation_id: str) -> Path:
        return self.base_dir / f"{conversation_id}.trace.jsonl"

    def save_trace(
        self,
        conversation_id: str,
        user_message: str,
        events: list[dict[str, Any]],
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        """保存一次完整的执行轨迹（同步写入）。"""
        self._ensure_dir()
        filepath = self._trace_path(conversation_id)

        tool_calls = sum(1 for e in events if e.get("type") == "tool_start")
        errors = sum(1 for e in events if e.get("type") == "error")
        has_reply = any(e.get("type") == "assistant_message" for e in events)

        entry = {
            "user_message": user_message,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
            "events": events,
            "summary": {
                "total_events": len(events),
                "tool_calls": tool_calls,
                "errors": errors,
                "has_assistant_reply": has_reply,
            },
        }

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def load_traces(self, conversation_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        """加载某个会话的所有执行轨迹。"""
        filepath = self._trace_path(conversation_id)
        if not filepath.exists():
            return []

        traces = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    traces.append(json.loads(line))
                except Exception:
                    logger.warning("跳过无法解析的 trace 行: %s", line[:100])

        if limit:
            traces = traces[-limit:]
        return traces

    def list_conversations(self) -> list[str]:
        """列出所有有 trace 记录的会话 ID。"""
        if not self.base_dir.exists():
            return []
        return [p.stem.replace(".trace", "") for p in self.base_dir.glob("*.trace.jsonl")]
