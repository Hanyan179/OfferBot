"""
SQLite 数据库连接管理

使用 aiosqlite 提供异步数据库操作，WAL 模式提升并发性能。
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

# schema.sql 与本文件同目录
_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


class Database:
    """SQLite 异步连接管理与基础操作。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """建立连接，启用 WAL 模式和外键约束。"""
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

    async def close(self) -> None:
        """关闭连接。"""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def init_schema(self) -> None:
        """读取 schema.sql 并执行，创建所有表。"""
        assert self._conn is not None, "Database not connected. Call connect() first."
        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        await self._conn.executescript(schema_sql)

    async def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        """执行读查询，返回 list[dict]。"""
        assert self._conn is not None, "Database not connected. Call connect() first."
        self._conn.row_factory = aiosqlite.Row
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def execute_write(self, sql: str, params: tuple = ()) -> int:
        """执行写查询，返回 lastrowid。"""
        assert self._conn is not None, "Database not connected. Call connect() first."
        cursor = await self._conn.execute(sql, params)
        await self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]
