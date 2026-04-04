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
        from web.app import _load_jobs, _load_interviews, _load_overview
        assert callable(_load_jobs)
        assert callable(_load_interviews)
        assert callable(_load_overview)


class TestHelperFunctions:
    def test_format_salary(self):
        from web.app import _format_salary
        assert _format_salary(30, 50) == "30-50K"
        assert _format_salary(30, None) == "30K+"
        assert _format_salary(None, 50) == "50K"
        assert _format_salary(None, None) == "面议"

    def test_stage_color(self):
        from web.app import _stage_color
        assert _stage_color("offer") == "green"
        assert _stage_color("rejected") == "red"
        assert _stage_color("withdrawn") == "red"
        assert _stage_color("round_1") == "green"
        assert _stage_color("applied") == "yellow"

    def test_stage_labels(self):
        from web.app import STAGE_LABELS
        assert STAGE_LABELS["applied"] == "已投递"
        assert STAGE_LABELS["offer"] == "Offer"

    def test_resume_loader(self):
        from web.app import _load_active_resume
        assert callable(_load_active_resume)


class TestTemplateFiles:
    def test_templates_exist(self):
        tpl_dir = Path(__file__).resolve().parent.parent / "web" / "templates"
        for name in ["base.html", "jobs.html", "resume.html", "interviews.html", "overview.html"]:
            assert (tpl_dir / name).exists(), f"{name} not found"


class TestChatModule:
    def test_chat_import(self):
        from web.chat import SCENARIO_CARDS, handle_user_message
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


class TestLoadInterviews:
    """Test _load_interviews reads from SQLite correctly."""

    @pytest_asyncio.fixture
    async def db(self, tmp_path):
        from db.database import Database
        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        await db.init_schema()
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_empty_db(self, db):
        from web.app import _load_interviews
        funnel, interviews = await _load_interviews(db)
        assert funnel[0]["count"] == 0  # 投递 = 0
        assert interviews == []

    @pytest.mark.asyncio
    async def test_with_applications(self, db):
        from web.app import _load_interviews
        await db.execute_write(
            "INSERT INTO jobs (url, title, company) VALUES (?, ?, ?)",
            ("https://a.com/1", "AI工程师", "字节跳动"),
        )
        await db.execute_write(
            "INSERT INTO applications (job_id, status) VALUES (?, ?)", (1, "sent"),
        )
        funnel, interviews = await _load_interviews(db)
        assert funnel[0]["count"] == 1  # 投递 = 1
        assert len(interviews) == 1
        assert interviews[0]["title"] == "AI工程师"
        assert interviews[0]["stage"] == "applied"
        assert interviews[0]["stage_label"] == "已投递"

    @pytest.mark.asyncio
    async def test_with_interview_tracking(self, db):
        from web.app import _load_interviews
        await db.execute_write(
            "INSERT INTO jobs (url, title, company) VALUES (?, ?, ?)",
            ("https://a.com/1", "NLP算法", "阿里"),
        )
        await db.execute_write(
            "INSERT INTO applications (job_id, status) VALUES (?, ?)", (1, "sent"),
        )
        await db.execute_write(
            "INSERT INTO interview_tracking (application_id, stage) VALUES (?, ?)",
            (1, "round_2"),
        )
        await db.execute_write(
            "INSERT INTO interview_stage_log (application_id, from_stage, to_stage) VALUES (?, ?, ?)",
            (1, "applied", "viewed"),
        )
        await db.execute_write(
            "INSERT INTO interview_stage_log (application_id, from_stage, to_stage) VALUES (?, ?, ?)",
            (1, "viewed", "round_2"),
        )
        funnel, interviews = await _load_interviews(db)
        assert interviews[0]["stage"] == "round_2"
        assert interviews[0]["stage_label"] == "二面"


class TestLoadOverview:
    """Test _load_overview reads from SQLite correctly."""

    @pytest_asyncio.fixture
    async def db(self, tmp_path):
        from db.database import Database
        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        await db.init_schema()
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_empty_db(self, db):
        from web.app import _load_overview
        result = await _load_overview(db)
        assert result["stats"]["active"] == 0
        assert result["stats"]["offers"] == 0
        assert result["cards"] == []

    @pytest.mark.asyncio
    async def test_with_data(self, db):
        from web.app import _load_overview
        await db.execute_write(
            "INSERT INTO jobs (url, title, company, match_score) VALUES (?, ?, ?, ?)",
            ("https://a.com/1", "AI工程师", "字节跳动", 92.0),
        )
        await db.execute_write(
            "INSERT INTO applications (job_id, status) VALUES (?, ?)", (1, "sent"),
        )
        result = await _load_overview(db)
        assert result["stats"]["active"] == 1
        assert len(result["cards"]) == 1
        assert result["cards"][0]["title"] == "AI工程师"
        assert result["cards"][0]["score"] == "92%"
        assert result["cards"][0]["stage"] == "已投递"

    @pytest.mark.asyncio
    async def test_offer_counted(self, db):
        from web.app import _load_overview
        await db.execute_write(
            "INSERT INTO jobs (url, title, company) VALUES (?, ?, ?)",
            ("https://a.com/1", "岗位A", "公司A"),
        )
        await db.execute_write(
            "INSERT INTO applications (job_id, status) VALUES (?, ?)", (1, "sent"),
        )
        await db.execute_write(
            "INSERT INTO interview_tracking (application_id, stage) VALUES (?, ?)",
            (1, "offer"),
        )
        result = await _load_overview(db)
        assert result["stats"]["offers"] == 1
        assert result["stats"]["active"] == 0  # offer is terminal
