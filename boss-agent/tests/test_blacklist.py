"""blacklist 模块单元测试"""

import pytest
import pytest_asyncio

from db.database import Database
from tools.data.blacklist import (
    AddToBlacklistTool,
    RemoveFromBlacklistTool,
    get_blacklist,
    is_blacklisted,
)


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()


@pytest.fixture
def add_tool():
    return AddToBlacklistTool()


@pytest.fixture
def remove_tool():
    return RemoveFromBlacklistTool()


# ---------------------------------------------------------------------------
# 元数据
# ---------------------------------------------------------------------------

class TestAddToBlacklistMeta:
    def test_name(self, add_tool):
        assert add_tool.name == "add_to_blacklist"

    def test_category(self, add_tool):
        assert add_tool.category == "data"

    def test_not_concurrency_safe(self, add_tool):
        assert add_tool.is_concurrency_safe is False

    def test_company_required(self, add_tool):
        assert "company" in add_tool.parameters_schema["required"]


class TestRemoveFromBlacklistMeta:
    def test_name(self, remove_tool):
        assert remove_tool.name == "remove_from_blacklist"

    def test_not_concurrency_safe(self, remove_tool):
        assert remove_tool.is_concurrency_safe is False


# ---------------------------------------------------------------------------
# AddToBlacklistTool
# ---------------------------------------------------------------------------

class TestAddToBlacklist:
    @pytest.mark.asyncio
    async def test_add_company(self, db, add_tool):
        result = await add_tool.execute({"company": "坏公司"}, {"db": db})
        assert result["success"] is True
        assert result["company"] == "坏公司"
        assert await is_blacklisted(db, "坏公司")

    @pytest.mark.asyncio
    async def test_add_with_reason(self, db, add_tool):
        await add_tool.execute(
            {"company": "坏公司", "reason": "拖欠工资"}, {"db": db}
        )
        bl = await get_blacklist(db)
        assert len(bl) == 1
        assert bl[0]["reason"] == "拖欠工资"

    @pytest.mark.asyncio
    async def test_add_duplicate_ignored(self, db, add_tool):
        ctx = {"db": db}
        await add_tool.execute({"company": "坏公司"}, ctx)
        await add_tool.execute({"company": "坏公司"}, ctx)
        bl = await get_blacklist(db)
        assert len(bl) == 1


# ---------------------------------------------------------------------------
# RemoveFromBlacklistTool
# ---------------------------------------------------------------------------

class TestRemoveFromBlacklist:
    @pytest.mark.asyncio
    async def test_remove_existing(self, db, add_tool, remove_tool):
        ctx = {"db": db}
        await add_tool.execute({"company": "坏公司"}, ctx)
        result = await remove_tool.execute({"company": "坏公司"}, ctx)
        assert result["success"] is True
        assert result["removed"] is True
        assert not await is_blacklisted(db, "坏公司")

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, db, remove_tool):
        result = await remove_tool.execute({"company": "不存在"}, {"db": db})
        assert result["success"] is True
        assert result["removed"] is False


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

class TestHelpers:
    @pytest.mark.asyncio
    async def test_get_blacklist_empty(self, db):
        bl = await get_blacklist(db)
        assert bl == []

    @pytest.mark.asyncio
    async def test_get_blacklist_multiple(self, db, add_tool):
        ctx = {"db": db}
        await add_tool.execute({"company": "A公司"}, ctx)
        await add_tool.execute({"company": "B公司"}, ctx)
        bl = await get_blacklist(db)
        assert len(bl) == 2

    @pytest.mark.asyncio
    async def test_is_blacklisted_false(self, db):
        assert not await is_blacklisted(db, "好公司")

    @pytest.mark.asyncio
    async def test_is_blacklisted_true(self, db, add_tool):
        await add_tool.execute({"company": "坏公司"}, {"db": db})
        assert await is_blacklisted(db, "坏公司")
