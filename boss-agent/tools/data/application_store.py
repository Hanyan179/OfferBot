"""
投递记录 CRUD 工具

SaveApplicationTool: 保存投递记录到数据库
辅助函数: get_application, get_applications_by_job, update_application_status
"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool
from db.database import Database


class SaveApplicationTool(Tool):
    """保存投递记录到数据库。"""

    @property
    def name(self) -> str:
        return "save_application"

    @property
    def display_name(self) -> str:
        return "保存投递记录"

    @property
    def description(self) -> str:
        return "记录投递信息"

    @property
    def category(self) -> str:
        return "data"

    @property
    def is_concurrency_safe(self) -> bool:
        return False

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "integer", "description": "关联的岗位 ID"},
                "resume_id": {"type": "integer", "description": "使用的简历版本 ID"},
                "match_result_id": {"type": "integer", "description": "关联的匹配分析 ID"},
                "greeting": {"type": "string", "description": "打招呼语"},
                "greeting_strategy": {"type": "string", "description": "打招呼策略说明"},
                "status": {
                    "type": "string",
                    "description": "投递状态（pending/sent/failed）",
                    "default": "pending",
                },
                "applied_at": {"type": "string", "description": "投递时间（ISO 格式）"},
                "error_message": {"type": "string", "description": "错误信息"},
            },
            "required": ["job_id"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        """插入投递记录，返回 {"application_id": int}。"""
        db: Database = context["db"]

        job_id = params["job_id"]
        resume_id = params.get("resume_id")
        match_result_id = params.get("match_result_id")
        greeting = params.get("greeting")
        greeting_strategy = params.get("greeting_strategy")
        status = params.get("status", "pending")
        applied_at = params.get("applied_at")
        error_message = params.get("error_message")

        app_id = await db.execute_write(
            "INSERT INTO applications "
            "(job_id, resume_id, match_result_id, greeting, greeting_strategy, status, applied_at, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, resume_id, match_result_id, greeting, greeting_strategy, status, applied_at, error_message),
        )
        return {"application_id": app_id}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def get_application(db: Database, app_id: int) -> dict | None:
    """根据 ID 获取单条投递记录。"""
    rows = await db.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
    return rows[0] if rows else None


async def get_applications_by_job(db: Database, job_id: int) -> list[dict]:
    """获取某个岗位的所有投递记录。"""
    return await db.execute(
        "SELECT * FROM applications WHERE job_id = ? ORDER BY id", (job_id,)
    )


async def update_application_status(
    db: Database,
    app_id: int,
    status: str,
    error_message: str | None = None,
) -> None:
    """更新投递状态，可选更新错误信息。"""
    if error_message is not None:
        await db.execute_write(
            "UPDATE applications SET status = ?, error_message = ? WHERE id = ?",
            (status, error_message, app_id),
        )
    else:
        await db.execute_write(
            "UPDATE applications SET status = ? WHERE id = ?",
            (status, app_id),
        )
