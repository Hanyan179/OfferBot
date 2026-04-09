"""Tests for resume API endpoints (PUT /api/resume, GET /api/resume/export/docx)."""

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import Database
from web.app import app


@pytest_asyncio.fixture
async def db(tmp_path):
    """Create a fresh in-memory database for each test."""
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def client(db):
    """Create an httpx AsyncClient wired to the FastAPI app with a test DB."""
    app.state.db = db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestPutApiResume:
    """PUT /api/resume endpoint tests."""

    @pytest.mark.asyncio
    async def test_update_scalar_fields(self, client, db):
        # Seed an active resume
        await db.execute_write(
            "INSERT INTO resumes (name, is_active) VALUES (?, 1)", ("旧名",)
        )
        resp = await client.put("/api/resume", json={"name": "新名", "city": "北京"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "name" in body["fields"]
        assert "city" in body["fields"]

        # Verify DB
        rows = await db.execute("SELECT name, city FROM resumes WHERE is_active = 1")
        assert rows[0]["name"] == "新名"
        assert rows[0]["city"] == "北京"

    @pytest.mark.asyncio
    async def test_auto_create_resume_when_none_exists(self, client, db):
        """需求 6.7: 无活跃简历时自动创建。"""
        resp = await client.put("/api/resume", json={"name": "张三", "city": "上海"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "name" in body["fields"]

        rows = await db.execute("SELECT name, city FROM resumes WHERE is_active = 1")
        assert len(rows) == 1
        assert rows[0]["name"] == "张三"
        assert rows[0]["city"] == "上海"

    @pytest.mark.asyncio
    async def test_auto_create_job_preferences(self, client, db):
        """需求 5.5: 首次保存求职意向自动创建 job_preferences 记录。"""
        await db.execute_write(
            "INSERT INTO resumes (name, is_active) VALUES (?, 1)", ("用户",)
        )
        prefs = {
            "target_cities": ["上海", "北京"],
            "salary_min": 20,
            "salary_max": 35,
        }
        resp = await client.put("/api/resume", json={"job_preferences": prefs})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "job_preferences" in body["fields"]

        rows = await db.execute("SELECT * FROM job_preferences WHERE is_active = 1")
        assert len(rows) == 1
        assert rows[0]["salary_min"] == 20
        assert rows[0]["salary_max"] == 35

    @pytest.mark.asyncio
    async def test_update_list_fields(self, client, db):
        await db.execute_write(
            "INSERT INTO resumes (name, is_active) VALUES (?, 1)", ("用户",)
        )
        work_exp = [{"company": "公司A", "role": "工程师"}]
        resp = await client.put("/api/resume", json={"work_experience": work_exp})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "work_experience" in body["fields"]

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self, client):
        resp = await client.put(
            "/api/resume",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert resp.json()["ok"] is False


class TestGetExportDocx:
    """GET /api/resume/export/docx endpoint tests."""

    @pytest.mark.asyncio
    async def test_export_docx_success(self, client, db):
        await db.execute_write(
            "INSERT INTO resumes (name, city, is_active) VALUES (?, ?, 1)",
            ("测试用户", "上海"),
        )
        resp = await client.get("/api/resume/export/docx")
        assert resp.status_code == 200
        assert "application/vnd.openxmlformats" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]
        # DOCX files start with PK zip magic bytes
        assert resp.content[:2] == b"PK"

    @pytest.mark.asyncio
    async def test_export_docx_no_resume_returns_404(self, client, db):
        """需求 7.7: 无活跃简历时返回 404。"""
        resp = await client.get("/api/resume/export/docx")
        assert resp.status_code == 404
        body = resp.json()
        assert body["ok"] is False
