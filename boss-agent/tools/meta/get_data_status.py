"""
get_data_status 元工具

查询当前用户的数据状态（画像、岗位、JD、投递、记忆），
帮助 LLM 判断该引导用户做什么。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tool_registry import Tool


class GetDataStatusTool(Tool):
    """获取当前用户数据状态的元工具。"""

    @property
    def name(self) -> str:
        return "get_data_status"

    @property
    def display_name(self) -> str:
        return "数据状态"

    @property
    def description(self) -> str:
        return "获取当前用户的数据状态，用于判断该引导用户做什么。"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, params: dict, context: Any) -> dict:
        db = context.get("db")
        if not db:
            return {"success": False, "error": "数据库不可用"}
        try:
            rows = await db.execute(
                "SELECT COUNT(*) AS cnt FROM resumes WHERE is_active = 1"
            )
            has_profile = rows[0]["cnt"] > 0

            rows = await db.execute("SELECT COUNT(*) AS cnt FROM jobs")
            job_count = rows[0]["cnt"]

            rows = await db.execute(
                "SELECT COUNT(*) AS cnt FROM jobs WHERE jd IS NOT NULL AND jd != ''"
            )
            jd_count = rows[0]["cnt"]

            rows = await db.execute("SELECT COUNT(*) AS cnt FROM applications")
            application_count = rows[0]["cnt"]

            memory_dir = Path(__file__).parent.parent.parent / "data" / "记忆画像"
            memory_category_count = (
                len(list(memory_dir.glob("*.md"))) if memory_dir.is_dir() else 0
            )

            return {
                "success": True,
                "has_profile": has_profile,
                "job_count": job_count,
                "jd_count": jd_count,
                "application_count": application_count,
                "memory_category_count": memory_category_count,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
