"""
Unit tests for QueryJobsTool fixes.

Deterministic tests verifying:
- salary_min filtering uses salary_min >= N (not salary_max >= N)
- Return fields are exactly 11 specified keys
- education exact match filtering
- experience LIKE fuzzy match filtering
- company_industry LIKE fuzzy match filtering
- salary_max filtering unchanged (salary_min <= M)
- Empty result format: {"success": true, "count": 0, "jobs": []}
- limit cap at 50

Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4
"""

from __future__ import annotations

import asyncio

import pytest

from db.database import Database
from tools.data.query_jobs import QueryJobsTool

EXPECTED_KEYS = {
    "id", "url", "title", "company", "salary_min", "salary_max",
    "salary_months", "city", "experience", "education", "match_score",
}


def _run_async(coro):
    """Helper to run async code in sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


INSERT_SQL = """
    INSERT INTO jobs (
        url, platform, title, company,
        salary_min, salary_max, salary_months, city, district, work_type,
        experience, experience_min, experience_max, education,
        skills, skills_must, skills_preferred, responsibilities,
        company_size, company_industry, company_stage, company_description,
        recruiter_name, recruiter_title, benefits, tags,
        raw_jd, structured_jd, match_score, match_detail
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


async def _setup_db_with_jobs(jobs_data: list[tuple]) -> Database:
    """Create in-memory DB, init schema, insert provided jobs."""
    db = Database(":memory:")
    await db.connect()
    await db.init_schema()
    for job in jobs_data:
        await db.execute_write(INSERT_SQL, job)
    return db


def _make_job(
    url: str,
    title: str = "工程师",
    company: str = "公司",
    salary_min: int = 10,
    salary_max: int = 30,
    salary_months: int = 13,
    city: str = "上海",
    experience: str = "1-3年",
    education: str = "本科",
    company_industry: str = "互联网",
    match_score: float = 80.0,
) -> tuple:
    """Build a full 30-column job tuple with sensible defaults."""
    return (
        url, "boss", title, company,
        salary_min, salary_max, salary_months, city, "浦东", "full_time",
        experience, 1, 3, education,
        "Python", None, None, None,
        None, company_industry, None, None,
        None, None, None, None,
        "raw jd", None, match_score, None,
    )


# ---------------------------------------------------------------------------
# Test: salary_min 过滤 (Req 2.1)
# ---------------------------------------------------------------------------


class TestSalaryMinFilter:
    """salary_min=40 should only return jobs with salary_min >= 40."""

    def test_salary_min_filters_correctly(self):
        async def _check():
            jobs = [
                _make_job("https://j/1", salary_min=20, salary_max=50),
                _make_job("https://j/2", salary_min=40, salary_max=60),
            ]
            db = await _setup_db_with_jobs(jobs)
            try:
                result = await QueryJobsTool().execute(
                    {"salary_min": 40}, {"db": db}
                )
                assert result["success"] is True
                assert result["count"] == 1
                assert result["jobs"][0]["salary_min"] == 40
                assert result["jobs"][0]["salary_max"] == 60
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Test: 返回字段 (Req 2.2)
# ---------------------------------------------------------------------------


class TestReturnFields:
    """Returned job dicts should contain exactly 11 specified keys."""

    def test_return_fields_exactly_11(self):
        async def _check():
            jobs = [_make_job("https://j/1")]
            db = await _setup_db_with_jobs(jobs)
            try:
                result = await QueryJobsTool().execute({}, {"db": db})
                assert result["count"] == 1
                actual_keys = set(result["jobs"][0].keys())
                assert actual_keys == EXPECTED_KEYS, (
                    f"Expected {EXPECTED_KEYS}, got {actual_keys}. "
                    f"Extra: {actual_keys - EXPECTED_KEYS}, "
                    f"Missing: {EXPECTED_KEYS - actual_keys}"
                )
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Test: education 精确匹配 (Req 2.3)
# ---------------------------------------------------------------------------


class TestEducationExactMatch:
    """education='本科' should only return 本科 jobs, not 硕士."""

    def test_education_exact_filter(self):
        async def _check():
            jobs = [
                _make_job("https://j/1", education="本科", title="前端工程师"),
                _make_job("https://j/2", education="硕士", title="算法工程师"),
            ]
            db = await _setup_db_with_jobs(jobs)
            try:
                result = await QueryJobsTool().execute(
                    {"education": "本科"}, {"db": db}
                )
                assert result["success"] is True
                assert result["count"] == 1
                assert result["jobs"][0]["education"] == "本科"
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Test: experience 模糊匹配 (Req 2.3)
# ---------------------------------------------------------------------------


class TestExperienceFuzzyMatch:
    """experience='3-5年' should match via LIKE, filtering out '5-10年'."""

    def test_experience_like_filter(self):
        async def _check():
            jobs = [
                _make_job("https://j/1", experience="3-5年", title="后端"),
                _make_job("https://j/2", experience="5-10年", title="架构师"),
            ]
            db = await _setup_db_with_jobs(jobs)
            try:
                result = await QueryJobsTool().execute(
                    {"experience": "3-5年"}, {"db": db}
                )
                assert result["success"] is True
                assert result["count"] == 1
                assert "3-5年" in result["jobs"][0]["experience"]
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Test: company_industry 模糊匹配 (Req 2.3)
# ---------------------------------------------------------------------------


class TestCompanyIndustryFuzzyMatch:
    """company_industry='互联网' should match via LIKE, filtering out '金融'."""

    def test_company_industry_like_filter(self):
        async def _check():
            jobs = [
                _make_job("https://j/1", company_industry="互联网", title="前端"),
                _make_job("https://j/2", company_industry="金融", title="风控"),
            ]
            db = await _setup_db_with_jobs(jobs)
            try:
                result = await QueryJobsTool().execute(
                    {"company_industry": "互联网"}, {"db": db}
                )
                assert result["success"] is True
                assert result["count"] == 1
                # company_industry is not in the 11 returned fields,
                # so we verify by checking only 1 job returned (the 互联网 one)
                assert result["jobs"][0]["title"] == "前端"
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Test: salary_max 过滤不变 (Req 3.1)
# ---------------------------------------------------------------------------


class TestSalaryMaxPreservation:
    """salary_max=30 should only return jobs with salary_min <= 30."""

    def test_salary_max_filters_correctly(self):
        async def _check():
            jobs = [
                _make_job("https://j/1", salary_min=20, salary_max=50),
                _make_job("https://j/2", salary_min=40, salary_max=60),
            ]
            db = await _setup_db_with_jobs(jobs)
            try:
                result = await QueryJobsTool().execute(
                    {"salary_max": 30}, {"db": db}
                )
                assert result["success"] is True
                assert result["count"] == 1
                assert result["jobs"][0]["salary_min"] == 20
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Test: 空结果格式 (Req 3.4)
# ---------------------------------------------------------------------------


class TestEmptyResultFormat:
    """Non-matching query should return {"success": True, "count": 0, "jobs": []}."""

    def test_empty_result_format(self):
        async def _check():
            jobs = [_make_job("https://j/1", city="上海")]
            db = await _setup_db_with_jobs(jobs)
            try:
                result = await QueryJobsTool().execute(
                    {"city": "不存在的城市XYZ"}, {"db": db}
                )
                assert result == {"success": True, "count": 0, "jobs": []}
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Test: limit 上限 (Req 3.3)
# ---------------------------------------------------------------------------


class TestLimitCap:
    """limit=100 should return at most 50 jobs."""

    def test_limit_capped_at_50(self):
        async def _check():
            # Insert 60 jobs to exceed the cap
            jobs = [
                _make_job(f"https://j/{i}", title=f"岗位{i}")
                for i in range(60)
            ]
            db = await _setup_db_with_jobs(jobs)
            try:
                result = await QueryJobsTool().execute(
                    {"limit": 100}, {"db": db}
                )
                assert result["success"] is True
                assert result["count"] <= 50, (
                    f"limit=100 should cap at 50, got {result['count']}"
                )
            finally:
                await db.close()

        _run_async(_check())
