"""
全局任务状态 — 供前端任务面板轮询

TaskMonitor 更新状态，前端 /api/tasks 读取。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


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
        return {
            "task_id": self.task_id,
            "name": self.name,
            "platform": self.platform,
            "status": self.status,
            "progress_text": self.progress_text,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "data": self.data,
        }


class TaskStateStore:
    """线程安全的全局任务状态存储"""

    _instance: TaskStateStore | None = None

    def __init__(self) -> None:
        self._tasks: dict[str, TaskInfo] = {}
        self._lock = threading.Lock()

    @classmethod
    def get(cls) -> TaskStateStore:
        if cls._instance is None:
            cls._instance = TaskStateStore()
        return cls._instance

    def upsert(self, task: TaskInfo) -> None:
        with self._lock:
            self._tasks[task.task_id] = task

    def update_status(self, task_id: str, status: str, progress_text: str = "") -> None:
        with self._lock:
            t = self._tasks.get(task_id)
            if t:
                t.status = status
                if progress_text:
                    t.progress_text = progress_text
                if status in ("completed", "failed", "timeout"):
                    t.finished_at = datetime.now()

    def update_progress(self, task_id: str, text: str) -> None:
        with self._lock:
            t = self._tasks.get(task_id)
            if t:
                t.progress_text = text

    def remove(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)

    def get_all(self) -> list[dict]:
        with self._lock:
            return [t.to_dict() for t in self._tasks.values()]

    def get_active(self) -> list[dict]:
        now = datetime.now()
        with self._lock:
            result = []
            for t in self._tasks.values():
                # 已完成超过 5 分钟的不返回
                if t.finished_at and (now - t.finished_at) > timedelta(minutes=5):
                    continue
                result.append(t.to_dict())
            return result
