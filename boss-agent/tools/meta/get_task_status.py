"""
get_task_status — 任务面板状态查询工具

返回当天的所有任务执行情况，和前端任务面板展示的内容一致。
"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool


class GetTaskStatusTool(Tool):
    """查询当天任务面板中的任务执行情况。"""

    @property
    def name(self) -> str:
        return "get_task_status"

    @property
    def display_name(self) -> str:
        return "任务进度"

    @property
    def description(self) -> str:
        return "查询当天的任务执行情况（采集、投递等后台任务的状态和进度）。"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "meta"

    @property
    def context_deps(self) -> list[str]:
        return ["db"]

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, params: dict, context: Any) -> dict:
        db = context.get("db")
        if not db:
            return {"success": False, "message": "数据库不可用"}

        from datetime import date

        from services.task_state import TaskStateStore

        store = TaskStateStore(db)
        today = date.today().isoformat()

        try:
            rows = await db.execute(
                "SELECT * FROM tasks WHERE date(started_at) = ? "
                "ORDER BY started_at DESC",
                (today,),
            )
            tasks = [store._row_to_dict(r) for r in rows]

            running = sum(1 for t in tasks if t["status"] == "running")
            completed = sum(1 for t in tasks if t["status"] == "completed")
            failed = sum(1 for t in tasks if t["status"] == "failed")

            return {
                "success": True,
                "date": today,
                "tasks": tasks,
                "running": running,
                "completed": completed,
                "failed": failed,
                "total": len(tasks),
            }
        except Exception as e:
            return {"success": False, "message": str(e)}
