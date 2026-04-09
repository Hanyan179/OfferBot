"""
对话日志系统 — 按对话/轮次组织的结构化执行日志

目录结构：
    data/logs/{conversation_id}/
        turn-001.log
        turn-002.log
        ...

每个 turn 文件记录一次用户消息触发的完整 Agent 执行过程：
LLM 请求/响应/耗时/token、tool 调用详情、最终回复。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "logs"


class ConversationLogger:
    """按对话/轮次写日志文件。"""

    def __init__(self, conversation_id: str, base_dir: Path | None = None):
        self._conv_id = conversation_id
        self._dir = (base_dir or LOGS_DIR) / conversation_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._turn = self._next_turn_number()
        self._lines: list[str] = []
        self._start_time: float = 0

    def _next_turn_number(self) -> int:
        existing = list(self._dir.glob("turn-*.log"))
        return len(existing) + 1

    # ------------------------------------------------------------------
    # 轮次生命周期
    # ------------------------------------------------------------------

    def begin_turn(self, user_message: str) -> None:
        self._lines = []
        self._start_time = time.time()
        self._log(f"{'='*60}")
        self._log(f"TURN {self._turn}  |  {datetime.now().isoformat()}")
        self._log(f"{'='*60}")
        self._log(f"USER: {user_message}")
        self._log("")

    def end_turn(self, assistant_reply: str) -> None:
        elapsed = time.time() - self._start_time
        self._log(f"ASSISTANT: {assistant_reply}")
        self._log("")
        self._log(f"TURN {self._turn} COMPLETED  |  {elapsed:.1f}s total")
        self._flush()
        self._turn += 1

    # ------------------------------------------------------------------
    # 事件记录
    # ------------------------------------------------------------------

    def log_llm_request(self, model: str, message_count: int, has_tools: bool) -> None:
        self._log(f"[LLM REQUEST]  model={model}  messages={message_count}  tools={'yes' if has_tools else 'no'}")

    def log_llm_response(self, *, has_text: bool, tool_call_count: int,
                         duration_ms: int, token_usage: dict[str, int] | None = None,
                         has_thinking: bool = False) -> None:
        parts = [
            f"[LLM RESPONSE]  text={'yes' if has_text else 'no'}",
            f"tools={tool_call_count}",
            f"thinking={'yes' if has_thinking else 'no'}",
            f"duration={duration_ms}ms",
        ]
        if token_usage:
            parts.append(f"tokens(prompt={token_usage.get('prompt', '?')}, completion={token_usage.get('completion', '?')})")
        self._log("  ".join(parts))

    def log_llm_error(self, error: str) -> None:
        self._log(f"[LLM ERROR]  {error}")

    def log_tool_start(self, tool_name: str, args: dict[str, Any]) -> None:
        args_str = json.dumps(args, ensure_ascii=False)
        self._log(f"[TOOL START]  {tool_name}  args={args_str}")

    def log_tool_result(self, tool_name: str, *, success: bool, duration_ms: int,
                        result_preview: str = "") -> None:
        status = "OK" if success else "FAIL"
        self._log(f"[TOOL {status}]  {tool_name}  duration={duration_ms}ms  result={result_preview}")

    def log_thinking(self, content: str) -> None:
        self._log(f"[THINKING]  {content}")

    def log_event(self, msg: str) -> None:
        self._log(f"[EVENT]  {msg}")

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _log(self, line: str) -> None:
        self._lines.append(line)

    def _flush(self) -> None:
        filepath = self._dir / f"turn-{self._turn:03d}.log"
        with filepath.open("w", encoding="utf-8") as f:
            f.write("\n".join(self._lines) + "\n")
