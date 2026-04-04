"""export 模块单元测试"""

import csv

import pytest
import pytest_asyncio

from db.database import Database
from tools.data.export import CSV_HEADERS, ExportCSVTool


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def seed_data(db: Database):
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
        "INSERT INTO applications (job_id, greeting, status, applied_at) VALUES (?, ?, ?, ?)",
        (j1, "你好", "sent", "2024-01-15T10:00:00"),
    )
    a2 = await db.execute_write(
        "INSERT INTO applications (job_id, greeting, status, applied_at) VALUES (?, ?, ?, ?)",
        (j2, "您好", "pending", None),
    )
    return {"job_ids": [j1, j2], "app_ids": [a1, a2]}


@pytest.fixture
def tool():
    return ExportCSVTool()


# ---------------------------------------------------------------------------
# 元数据
# ---------------------------------------------------------------------------

class TestExportCSVToolMeta:
    def test_name(self, tool):
        assert tool.name == "export_csv"

    def test_category(self, tool):
        assert tool.category == "data"

    def test_concurrency_safe(self, tool):
        assert tool.is_concurrency_safe is True

    def test_output_path_required(self, tool):
        assert "output_path" in tool.parameters_schema["required"]


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------

class TestExportCSV:
    @pytest.mark.asyncio
    async def test_export_empty(self, db, tool, tmp_path):
        out = str(tmp_path / "out.csv")
        result = await tool.execute({"output_path": out}, {"db": db})
        assert result["success"] is True
        assert result["row_count"] == 0
        with open(out, encoding="utf-8") as f:
            reader = list(csv.reader(f))
        assert len(reader) == 1  # header only
        assert reader[0] == CSV_HEADERS

    @pytest.mark.asyncio
    async def test_export_with_data(self, db, seed_data, tool, tmp_path):
        out = str(tmp_path / "out.csv")
        result = await tool.execute({"output_path": out}, {"db": db})
        assert result["success"] is True
        assert result["row_count"] == 2
        assert result["path"] == out

        with open(out, encoding="utf-8") as f:
            reader = list(csv.reader(f))
        # header + 2 data rows
        assert len(reader) == 3
        assert reader[0] == CSV_HEADERS
        # Each row has same number of fields as header
        for row in reader[1:]:
            assert len(row) == len(CSV_HEADERS)

    @pytest.mark.asyncio
    async def test_export_field_values(self, db, seed_data, tool, tmp_path):
        out = str(tmp_path / "out.csv")
        await tool.execute({"output_path": out}, {"db": db})
        with open(out, encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
        assert reader[0]["title"] == "AI 工程师"
        assert reader[0]["company"] == "公司A"
        assert reader[0]["greeting"] == "你好"
        assert reader[1]["title"] == "后端开发"
