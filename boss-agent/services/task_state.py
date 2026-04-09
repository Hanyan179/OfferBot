"""
任务状态持久化 — SQLite 存储，供前端任务面板和 AI 查询

只有用户确认执行的操作和后台长任务才写入。
AI 即时调用的 Tool 不记录。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TaskInfo:
    """单个任务的状态"""
    task_id: str
    name: str
    platform: str
    status: str
    progress_text: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        elapsed = (self.finished_at or datetime.now()) - self.started_at
        return {
            "task_id": self.task_id,
            "name": self.name,
            "platform": self.platform,
            "status": self.status,
            "progress_text": self.progress_text,
            "elapsed_s": int(elapsed.total_seconds()),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "data": self.data,
        }


class TaskStateStore:
    """任务状态持久化存储，需要传入 db 实例"""

    def __init__(self, db) -> None:
        self._db = db

    async def upsert(self, task: TaskInfo) -> None:
        await self._db.execute_write(
            "INSERT INTO tasks (task_id, name, platform, status, progress_text, data, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(task_id) DO UPDATE SET name=?, platform=?, status=?, progress_text=?, data=?",
            (task.task_id, task.name, task.platform, task.status, task.progress_text,
             json.dumps(task.data, ensure_ascii=False), task.started_at.isoformat(),
             task.name, task.platform, task.status, task.progress_text,
             json.dumps(task.data, ensure_ascii=False)),
        )

    async def update_status(self, task_id: str, status: str, progress_text: str = "") -> None:
        finished = datetime.now().isoformat() if status in ("completed", "failed", "timeout") else None
        if progress_text:
            await self._db.execute_write(
                "UPDATE tasks SET status=?, progress_text=?, finished_at=? WHERE task_id=?",
                (status, progress_text, finished, task_id),
            )
        else:
            await self._db.execute_write(
                "UPDATE tasks SET status=?, finished_at=? WHERE task_id=?",
                (status, finished, task_id),
            )

    async def update_progress(self, task_id: str, text: str) -> None:
        await self._db.execute_write(
            "UPDATE tasks SET progress_text=? WHERE task_id=?", (text, task_id),
        )

    async def get_active(self) -> list[dict]:
        """运行中 + 最近 30 分钟完成的"""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(minutes=30)).isoformat()
        rows = await self._db.execute(
            "SELECT * FROM tasks WHERE status='running' "
            "OR (finished_at IS NOT NULL AND finished_at > ?) "
            "ORDER BY started_at DESC",
            (cutoff,),
        )
        return [self._row_to_dict(r) for r in rows]

    async def get_all(self, limit: int = 50) -> list[dict]:
        rows = await self._db.execute(
            "SELECT * FROM tasks ORDER BY started_at DESC LIMIT ?", (limit,)
        )
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(r) -> dict:
        started = datetime.fromisoformat(r["started_at"]) if r.get("started_at") else datetime.now()
        finished = datetime.fromisoformat(r["finished_at"]) if r.get("finished_at") else None
        elapsed = (finished or datetime.now()) - started
        return {
            "task_id": r["task_id"],
            "name": r["name"],
            "platform": r.get("platform", ""),
            "status": r["status"],
            "progress_text": r.get("progress_text", ""),
            "elapsed_s": int(elapsed.total_seconds()),
            "started_at": r.get("started_at"),
            "finished_at": r.get("finished_at"),
            "data": json.loads(r["data"]) if r.get("data") else {},
        }
