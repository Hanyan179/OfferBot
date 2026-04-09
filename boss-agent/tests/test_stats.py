"""stats 模块单元测试"""

import pytest
import pytest_asyncio

from db.database import Database
from tools.data.stats import GetStatsTool


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def seed_data(db: Database):
    """插入测试数据：2 家公司、3 个岗位、5 条投递，部分有面试状态。"""
    # 岗位
    j1 = await db.execute_write(
        "INSERT INTO jobs (url, title, company, match_score) VALUES (?, ?, ?, ?)",
        ("https://example.com/1", "AI 工程师", "公司A", 85.0),
    )
    j2 = await db.execute_write(
        "INSERT INTO jobs (url, title, company, match_score) VALUES (?, ?, ?, ?)",
        ("https://example.com/2", "后端开发", "公司A", 70.0),
    )
    j3 = await db.execute_write(
        "INSERT INTO jobs (url, title, company) VALUES (?, ?, ?)",
        ("https://example.com/3", "AI 工程师", "公司B"),
    )

    # 投递
    a1 = await db.execute_write(
        "INSERT INTO applications (job_id, status) VALUES (?, ?)", (j1, "sent")
    )
    a2 = await db.execute_write(
        "INSERT INTO applications (job_id, status) VALUES (?, ?)", (j2, "sent")
    )
    a3 = await db.execute_write(
        "INSERT INTO applications (job_id, status) VALUES (?, ?)", (j3, "sent")
    )
    a4 = await db.execute_write(
        "INSERT INTO applications (job_id, status) VALUES (?, ?)", (j1, "sent")
    )
    a5 = await db.execute_write(
        "INSERT INTO applications (job_id, status) VALUES (?, ?)", (j3, "sent")
    )

    return {"job_ids": [j1, j2, j3], "app_ids": [a1, a2, a3, a4, a5]}


@pytest.fixture
def tool():
    return GetStatsTool()


# ---------------------------------------------------------------------------
# 元数据
# ---------------------------------------------------------------------------

class TestGetStatsToolMeta:
    def test_name(self, tool):
        assert tool.name == "get_stats"

    def test_category(self, tool):
        assert tool.category == "data"

    def test_concurrency_safe(self, tool):
        assert tool.is_concurrency_safe is True


# ---------------------------------------------------------------------------
# 空数据库
# ---------------------------------------------------------------------------

class TestStatsEmpty:
    @pytest.mark.asyncio
    async def test_empty_db(self, db, tool):
        result = await tool.execute({}, {"db": db})
        stats = result["for_agent"]
        assert stats["total_applications"] == 0
        assert stats["total_replied"] == 0
        assert stats["reply_rate"] == 0.0
        assert stats["total_interviews"] == 0
        assert stats["interview_rate"] == 0.0
        assert stats["avg_match_score"] == 0.0
        assert stats["by_company"] == []
        assert stats["by_title"] == []


# ---------------------------------------------------------------------------
# 有数据
# ---------------------------------------------------------------------------

class TestStatsWithData:
    @pytest.mark.asyncio
    async def test_totals(self, db, seed_data, tool):
        result = await tool.execute({}, {"db": db})
        stats = result["for_agent"]
        assert stats["total_applications"] == 5
        assert stats["total_replied"] == 0
        assert stats["total_interviews"] == 0

    @pytest.mark.asyncio
    async def test_rates(self, db, seed_data, tool):
        result = await tool.execute({}, {"db": db})
        stats = result["for_agent"]
        assert stats["reply_rate"] == pytest.approx(0.0)
        assert stats["interview_rate"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_by_company(self, db, seed_data, tool):
        result = await tool.execute({}, {"db": db})
        stats = result["for_agent"]
        by_company = {r["company"]: r["count"] for r in stats["by_company"]}
        assert by_company["公司A"] == 3  # j1 + j2 + j1 again
        assert by_company["公司B"] == 2  # j3 twice

    @pytest.mark.asyncio
    async def test_by_title(self, db, seed_data, tool):
        result = await tool.execute({}, {"db": db})
        stats = result["for_agent"]
        by_title = {r["title"]: r["count"] for r in stats["by_title"]}
        assert by_title["AI 工程师"] == 4  # j1 twice + j3 twice
        assert by_title["后端开发"] == 1

    @pytest.mark.asyncio
    async def test_avg_match_score(self, db, seed_data, tool):
        result = await tool.execute({}, {"db": db})
        stats = result["for_agent"]
        # j1=85.0, j2=70.0, j3=None; 投递: j1×2, j2×1, j3×2
        # 有 match_score 的投递: j1(85)×2 + j2(70)×1 = 3 条
        # avg = (85+85+70)/3 = 80.0
        assert stats["avg_match_score"] == pytest.approx(80.0)
