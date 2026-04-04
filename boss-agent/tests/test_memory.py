"""memory 模块单元测试"""

import pytest
import pytest_asyncio

from agent.memory import Memory
from db.database import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def memory(db: Database):
    return Memory(db)


@pytest_asyncio.fixture
async def seed_data(db: Database):
    """插入岗位和投递数据供 history 测试使用。"""
    j1 = await db.execute_write(
        "INSERT INTO jobs (url, title, company, city, salary_min, salary_max, match_score) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("https://example.com/1", "AI 工程师", "公司A", "上海", 20, 40, 85.5),
    )
    j2 = await db.execute_write(
        "INSERT INTO jobs (url, title, company, city, salary_min, salary_max, match_score) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("https://example.com/2", "后端开发", "公司B", "北京", 15, 30, 72.0),
    )
    a1 = await db.execute_write(
        "INSERT INTO applications (job_id, greeting, status) VALUES (?, ?, ?)",
        (j1, "你好", "sent"),
    )
    a2 = await db.execute_write(
        "INSERT INTO applications (job_id, greeting, status) VALUES (?, ?, ?)",
        (j2, "您好", "pending"),
    )
    return {"job_ids": [j1, j2], "app_ids": [a1, a2]}


# ---------------------------------------------------------------------------
# 用户偏好
# ---------------------------------------------------------------------------

class TestPreferences:
    @pytest.mark.asyncio
    async def test_empty_preferences(self, memory):
        prefs = await memory.get_preferences()
        assert prefs == {}

    @pytest.mark.asyncio
    async def test_set_and_get(self, memory):
        await memory.set_preference("city", "上海")
        await memory.set_preference("salary_min", "20")
        prefs = await memory.get_preferences()
        assert prefs["city"] == "上海"
        assert prefs["salary_min"] == "20"

    @pytest.mark.asyncio
    async def test_overwrite(self, memory):
        await memory.set_preference("city", "上海")
        await memory.set_preference("city", "北京")
        prefs = await memory.get_preferences()
        assert prefs["city"] == "北京"


# ---------------------------------------------------------------------------
# 黑名单
# ---------------------------------------------------------------------------

class TestBlacklist:
    @pytest.mark.asyncio
    async def test_empty_blacklist(self, memory):
        bl = await memory.get_blacklist()
        assert bl == []

    @pytest.mark.asyncio
    async def test_add_and_get(self, memory):
        await memory.add_to_blacklist("坏公司")
        bl = await memory.get_blacklist()
        assert "坏公司" in bl

    @pytest.mark.asyncio
    async def test_add_with_reason(self, memory):
        await memory.add_to_blacklist("坏公司", reason="拖欠工资")
        bl = await memory.get_blacklist()
        assert "坏公司" in bl

    @pytest.mark.asyncio
    async def test_add_duplicate_ignored(self, memory):
        await memory.add_to_blacklist("坏公司")
        await memory.add_to_blacklist("坏公司")
        bl = await memory.get_blacklist()
        assert bl.count("坏公司") == 1

    @pytest.mark.asyncio
    async def test_remove(self, memory):
        await memory.add_to_blacklist("坏公司")
        removed = await memory.remove_from_blacklist("坏公司")
        assert removed is True
        bl = await memory.get_blacklist()
        assert "坏公司" not in bl

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, memory):
        removed = await memory.remove_from_blacklist("不存在")
        assert removed is False


# ---------------------------------------------------------------------------
# 投递历史
# ---------------------------------------------------------------------------

class TestApplicationHistory:
    @pytest.mark.asyncio
    async def test_empty_history(self, memory):
        history = await memory.get_application_history()
        assert history == []

    @pytest.mark.asyncio
    async def test_history_with_data(self, memory, seed_data):
        history = await memory.get_application_history()
        assert len(history) == 2
        # DESC order — most recent first
        assert history[0]["title"] == "后端开发"
        assert history[1]["title"] == "AI 工程师"

    @pytest.mark.asyncio
    async def test_history_limit(self, memory, seed_data):
        history = await memory.get_application_history(limit=1)
        assert len(history) == 1

    @pytest.mark.asyncio
    async def test_history_fields(self, memory, seed_data):
        history = await memory.get_application_history()
        row = history[0]
        for key in ("id", "job_id", "greeting", "status", "title", "company", "city"):
            assert key in row
