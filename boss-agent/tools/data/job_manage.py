"""
岗位数据管理工具 — 批量删除、清空、统计

让 AI 能帮用户清理垃圾数据。
"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool
from db.database import Database


class DeleteJobsTool(Tool):
    """批量删除岗位数据，支持按平台、天数、关键词筛选。"""

    @property
    def name(self) -> str:
        return "delete_jobs"

    @property
    def description(self) -> str:
        return (
            "批量删除本地岗位数据。支持按平台（liepin/zhilian）、"
            "天数（删除 N 天前的数据）、关键词、城市筛选。"
            "也可以传 delete_all=true 清空全部岗位数据。"
        )

    @property
    def category(self) -> str:
        return "data"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["liepin", "zhilian", "all"],
                    "description": "平台筛选，all 表示所有平台",
                },
                "older_than_days": {
                    "type": "integer",
                    "description": "删除 N 天前的数据（基于 discovered_at）",
                },
                "keyword": {
                    "type": "string",
                    "description": "按岗位标题关键词筛选删除",
                },
                "city": {
                    "type": "string",
                    "description": "按城市筛选删除",
                },
                "delete_all": {
                    "type": "boolean",
                    "description": "true=清空全部岗位数据（危险操作）",
                    "default": False,
                },
            },
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db: Database = context["db"]

        # 清空全部
        if params.get("delete_all"):
            count_rows = await db.execute("SELECT COUNT(*) as cnt FROM jobs")
            count = count_rows[0]["cnt"]
            await db.execute_write("DELETE FROM jobs")
            return {
                "success": True,
                "deleted": count,
                "message": f"已清空全部 {count} 条岗位数据",
            }

        # 构建条件
        clauses: list[str] = []
        values: list[Any] = []

        platform = params.get("platform")
        if platform and platform != "all":
            clauses.append("platform = ?")
            values.append(platform)

        days = params.get("older_than_days")
        if days is not None:
            clauses.append("discovered_at < datetime('now', ?)")
            values.append(f"-{days} days")

        keyword = params.get("keyword")
        if keyword:
            clauses.append("title LIKE ?")
            values.append(f"%{keyword}%")

        city = params.get("city")
        if city:
            clauses.append("city LIKE ?")
            values.append(f"%{city}%")

        if not clauses:
            return {
                "success": False,
                "error": "请至少指定一个筛选条件（platform、older_than_days、keyword、city），或使用 delete_all=true 清空全部",
            }

        where = " WHERE " + " AND ".join(clauses)

        # 先统计要删多少
        count_rows = await db.execute(
            f"SELECT COUNT(*) as cnt FROM jobs{where}", tuple(values)
        )
        count = count_rows[0]["cnt"]

        if count == 0:
            return {"success": True, "deleted": 0, "message": "没有匹配的数据需要删除"}

        # 执行删除
        await db.execute_write(f"DELETE FROM jobs{where}", tuple(values))

        return {
            "success": True,
            "deleted": count,
            "message": f"已删除 {count} 条岗位数据",
        }


class JobCountTool(Tool):
    """统计本地岗位数据数量。"""

    @property
    def name(self) -> str:
        return "job_count"

    @property
    def description(self) -> str:
        return "统计本地岗位数据数量，支持按平台、城市分组。"

    @property
    def category(self) -> str:
        return "data"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "enum": ["platform", "city", "none"],
                    "description": "分组方式",
                    "default": "none",
                },
            },
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db: Database = context["db"]
        group_by = params.get("group_by", "none")

        if group_by == "platform":
            rows = await db.execute(
                "SELECT platform, COUNT(*) as count FROM jobs GROUP BY platform ORDER BY count DESC"
            )
            total_rows = await db.execute("SELECT COUNT(*) as cnt FROM jobs")
            return {
                "success": True,
                "total": total_rows[0]["cnt"],
                "by_platform": rows,
            }
        elif group_by == "city":
            rows = await db.execute(
                "SELECT city, COUNT(*) as count FROM jobs GROUP BY city ORDER BY count DESC LIMIT 20"
            )
            total_rows = await db.execute("SELECT COUNT(*) as cnt FROM jobs")
            return {
                "success": True,
                "total": total_rows[0]["cnt"],
                "by_city": rows,
            }
        else:
            rows = await db.execute("SELECT COUNT(*) as cnt FROM jobs")
            return {"success": True, "total": rows[0]["cnt"]}
