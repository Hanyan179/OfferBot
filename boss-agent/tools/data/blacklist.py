"""
黑名单 CRUD 工具

AddToBlacklistTool: 将公司加入黑名单
RemoveFromBlacklistTool: 将公司从黑名单移除
辅助函数: get_blacklist, is_blacklisted
"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool
from db.database import Database


class AddToBlacklistTool(Tool):
    """将公司加入黑名单。"""

    @property
    def name(self) -> str:
        return "add_to_blacklist"

    @property
    def description(self) -> str:
        return "将公司加入黑名单"

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
                "company": {"type": "string", "description": "公司名称"},
                "reason": {"type": "string", "description": "拉黑原因"},
            },
            "required": ["company"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db: Database = context["db"]
        company = params["company"]
        reason = params.get("reason")

        await db.execute_write(
            "INSERT OR IGNORE INTO blacklist (company, reason) VALUES (?, ?)",
            (company, reason),
        )
        return {"success": True, "company": company}


class RemoveFromBlacklistTool(Tool):
    """将公司从黑名单移除。"""

    @property
    def name(self) -> str:
        return "remove_from_blacklist"

    @property
    def description(self) -> str:
        return "将公司从黑名单移除"

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
                "company": {"type": "string", "description": "公司名称"},
            },
            "required": ["company"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db: Database = context["db"]
        company = params["company"]

        assert db._conn is not None, "Database not connected."
        cursor = await db._conn.execute(
            "DELETE FROM blacklist WHERE company = ?", (company,)
        )
        await db._conn.commit()
        removed = cursor.rowcount > 0

        return {"success": True, "removed": removed}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def get_blacklist(db: Database) -> list[dict]:
    """返回所有黑名单公司。"""
    return await db.execute("SELECT * FROM blacklist ORDER BY id")


async def is_blacklisted(db: Database, company: str) -> bool:
    """检查公司是否在黑名单中。"""
    rows = await db.execute(
        "SELECT 1 FROM blacklist WHERE company = ?", (company,)
    )
    return len(rows) > 0
