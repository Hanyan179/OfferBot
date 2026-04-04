"""
持久记忆模块

Memory 类：用户偏好读写、黑名单管理、投递历史查询
"""

from __future__ import annotations

from db.database import Database


class Memory:
    """持久记忆：用户偏好、黑名单、投递历史"""

    def __init__(self, db: Database):
        self.db = db

    async def get_preferences(self) -> dict:
        """获取所有用户偏好 as {key: value}"""
        rows = await self.db.execute("SELECT key, value FROM user_preferences")
        return {r["key"]: r["value"] for r in rows}

    async def set_preference(self, key: str, value: str) -> None:
        """设置单个用户偏好 (INSERT OR REPLACE)"""
        await self.db.execute_write(
            "INSERT OR REPLACE INTO user_preferences (key, value, updated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (key, value),
        )

    async def get_blacklist(self) -> list[str]:
        """获取黑名单公司列表"""
        rows = await self.db.execute("SELECT company FROM blacklist ORDER BY id")
        return [r["company"] for r in rows]

    async def add_to_blacklist(self, company: str, reason: str | None = None) -> None:
        """将公司加入黑名单"""
        await self.db.execute_write(
            "INSERT OR IGNORE INTO blacklist (company, reason) VALUES (?, ?)",
            (company, reason),
        )

    async def remove_from_blacklist(self, company: str) -> bool:
        """将公司从黑名单移除，返回是否实际删除了记录"""
        assert self.db._conn is not None, "Database not connected."
        cursor = await self.db._conn.execute(
            "DELETE FROM blacklist WHERE company = ?", (company,)
        )
        await self.db._conn.commit()
        return cursor.rowcount > 0

    async def get_application_history(self, limit: int = 100) -> list[dict]:
        """获取最近投递记录 (JOIN jobs for context)"""
        return await self.db.execute(
            "SELECT a.id, a.job_id, a.resume_id, a.greeting, a.status, a.applied_at, "
            "j.title, j.company, j.city, j.salary_min, j.salary_max, j.match_score "
            "FROM applications a JOIN jobs j ON a.job_id = j.id "
            "ORDER BY a.id DESC LIMIT ?",
            (limit,),
        )
