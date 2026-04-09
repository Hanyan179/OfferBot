"""Tests for the FastAPI + Chainlit Boss Agent app."""

import sys
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestAppImport:
    def test_fastapi_app_exists(self):
        from web.app import app
        assert app is not None
        assert app.title == "Boss Agent"

    def test_data_helpers_exist(self):
        from web.app import _load_jobs
        assert callable(_load_jobs)


class TestHelperFunctions:
    def test_format_salary(self):
        from web.app import _format_salary
        assert _format_salary(30, 50) == "30-50K"
        assert _format_salary(30, None) == "30K+"
        assert _format_salary(None, 50) == "50K"
        assert _format_salary(None, None) == "面议"

    def test_resume_loader(self):
        from web.app import _load_active_resume
        assert callable(_load_active_resume)


class TestTemplateFiles:
    def test_templates_exist(self):
        tpl_dir = Path(__file__).resolve().parent.parent / "web" / "templates"
        for name in ["base.html", "jobs.html", "resume.html"]:
            assert (tpl_dir / name).exists(), f"{name} not found"


class TestChatModule:
    def test_chat_import(self):
        from web.chat import SCENARIO_CARDS
        assert len(SCENARIO_CARDS) == 4

    def test_handle_is_coroutine(self):
        import inspect

        from web.chat import handle_user_message
        assert inspect.iscoroutinefunction(handle_user_message)


class TestLoadActiveResume:
    """Test _load_active_resume reads from SQLite correctly."""

    @pytest_asyncio.fixture
    async def db(self, tmp_path):
        from db.database import Database
        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        await db.init_schema()
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_empty_db_returns_defaults(self, db):
        from web.app import _load_active_resume
        result = await _load_active_resume(db)
        assert result["name"] is None
        assert result["tech_stack"] == []
        assert result["work_experience"] == []

    @pytest.mark.asyncio
    async def test_loads_active_resume(self, db):
        import json

        from web.app import _load_active_resume
        skills = ["Python", "FastAPI", "RAG"]
        work_exp = [{"company": "TestCo", "role": "Dev", "duration": "2023-now", "description": "Built stuff"}]
        await db.execute_write(
            "INSERT INTO resumes (name, city, education_level, years_of_experience, "
            "skills_flat, work_experience, is_active) VALUES (?, ?, ?, ?, ?, ?, 1)",
            ("测试用户", "上海", "本科", 3, json.dumps(skills, ensure_ascii=False),
             json.dumps(work_exp, ensure_ascii=False)),
        )
        result = await _load_active_resume(db)
        assert result["name"] == "测试用户"
        assert result["city"] == "上海"
        assert result["education"] == "本科"
        assert result["experience"] == "3年"
        assert result["tech_stack"] == skills
        assert len(result["work_experience"]) == 1
        assert result["work_experience"][0]["company"] == "TestCo"

    @pytest.mark.asyncio
    async def test_ignores_inactive_resume(self, db):
        from web.app import _load_active_resume
        await db.execute_write(
            "INSERT INTO resumes (name, is_active) VALUES (?, 0)", ("旧简历",)
        )
        result = await _load_active_resume(db)
        assert result["name"] is None

    @pytest.mark.asyncio
    async def test_tech_stack_dict_flattened(self, db):
        import json

        from web.app import _load_active_resume
        tech_dict = {"AI": ["PyTorch", "LangChain"], "Web": ["FastAPI"]}
        await db.execute_write(
            "INSERT INTO resumes (name, tech_stack, is_active) VALUES (?, ?, 1)",
            ("用户", json.dumps(tech_dict, ensure_ascii=False)),
        )
        result = await _load_active_resume(db)
        assert "PyTorch" in result["tech_stack"]
        assert "LangChain" in result["tech_stack"]
        assert "FastAPI" in result["tech_stack"]

    @pytest.mark.asyncio
    async def test_picks_latest_active_resume(self, db):
        from web.app import _load_active_resume
        await db.execute_write("INSERT INTO resumes (name, is_active) VALUES (?, 1)", ("旧版",))
        await db.execute_write("INSERT INTO resumes (name, is_active) VALUES (?, 1)", ("新版",))
        result = await _load_active_resume(db)
        assert result["name"] == "新版"


class TestLoadJobs:
    """Test _load_jobs reads from SQLite correctly."""

    @pytest_asyncio.fixture
    async def db(self, tmp_path):
        from db.database import Database
        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        await db.init_schema()
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, db):
        from web.app import _load_jobs
        result = await _load_jobs(db)
        assert result == []

    @pytest.mark.asyncio
    async def test_loads_jobs(self, db):
        from web.app import _load_jobs
        await db.execute_write(
            "INSERT INTO jobs (url, title, company, salary_min, salary_max, city, match_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("https://example.com/job1", "AI工程师", "字节跳动", 30, 50, "上海", 92.5),
        )
        result = await _load_jobs(db)
        assert len(result) == 1
        assert result[0]["title"] == "AI工程师"
        assert result[0]["company"] == "字节跳动"
        assert result[0]["salary"] == "30-50K"
        assert result[0]["city"] == "上海"
        assert result[0]["score"] == 92  # round(92.5) = 92 (banker's rounding)

    @pytest.mark.asyncio
    async def test_jobs_sorted_by_match_score(self, db):
        from web.app import _load_jobs
        await db.execute_write(
            "INSERT INTO jobs (url, title, company, match_score) VALUES (?, ?, ?, ?)",
            ("https://a.com/1", "低分岗位", "A公司", 60.0),
        )
        await db.execute_write(
            "INSERT INTO jobs (url, title, company, match_score) VALUES (?, ?, ?, ?)",
            ("https://a.com/2", "高分岗位", "B公司", 95.0),
        )
        result = await _load_jobs(db)
        assert result[0]["title"] == "高分岗位"
        assert result[1]["title"] == "低分岗位"

    @pytest.mark.asyncio
    async def test_jobs_null_score(self, db):
        from web.app import _load_jobs
        await db.execute_write(
            "INSERT INTO jobs (url, title, company) VALUES (?, ?, ?)",
            ("https://a.com/1", "无评分岗位", "C公司"),
        )
        result = await _load_jobs(db)
        assert result[0]["score"] == 0



