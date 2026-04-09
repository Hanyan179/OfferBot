"""
Property-based preservation tests for QueryJobsTool.

These tests verify behaviors that MUST remain unchanged after the bugfix.
They should PASS on the current UNFIXED code (observation-first methodology).

Property 2a: keyword LIKE 匹配
  For all keyword values, returned jobs' title SHALL contain keyword (case-insensitive LIKE).
  **Validates: Requirements 3.1, 3.2**

Property 2b: city LIKE 匹配
  For all city values, returned jobs' city SHALL contain city.
  **Validates: Requirements 3.2**

Property 2c: company LIKE 匹配
  For all company values, returned jobs' company SHALL contain company.
  **Validates: Requirements 3.2**

Property 2d: salary_max 过滤
  For all salary_max=M, returned jobs SHALL have salary_min <= M.
  **Validates: Requirements 3.1**

Property 2e: limit 上限
  For all limit=L, returned count SHALL be <= min(L, 50).
  **Validates: Requirements 3.3**

Property 2f: 返回格式
  Result format SHALL always be {"success": bool, "count": int, "jobs": list}.
  **Validates: Requirements 3.4**
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from db.database import Database
from tools.data.query_jobs import QueryJobsTool


def _run_async(coro):
    """Helper to run async code in hypothesis tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _setup_db_with_jobs() -> Database:
    """Create an in-memory DB, init schema, and insert diverse test jobs."""
    db = Database(":memory:")
    await db.connect()
    await db.init_schema()

    # Insert diverse jobs to make preservation properties meaningful.
    # Titles, cities, companies, salaries are varied so that LIKE matching
    # and salary filtering can be exercised by Hypothesis-generated values.
    jobs = [
        # (url, platform, title, company, salary_min, salary_max, salary_months,
        #  city, district, work_type, experience, experience_min, experience_max,
        #  education, skills, skills_must, skills_preferred, responsibilities,
        #  company_size, company_industry, company_stage, company_description,
        #  recruiter_name, recruiter_title, benefits, tags,
        #  raw_jd, structured_jd, match_score, match_detail)
        ("https://example.com/job/1", "boss", "AI Engineer", "AlphaCorp",
         10, 30, 13, "Shanghai", "Pudong", "full_time",
         "1-3年", 1, 3, "本科", "Python", None, None, None,
         None, "互联网", None, None, None, None, None, None,
         "raw jd 1", None, 85.0, None),
        ("https://example.com/job/2", "boss", "Backend Dev", "BetaInc",
         20, 50, 14, "Beijing", "Chaoyang", "full_time",
         "3-5年", 3, 5, "硕士", "Java", None, None, None,
         None, "金融", None, None, None, None, None, None,
         "raw jd 2", None, 75.0, None),
        ("https://example.com/job/3", "boss", "Fullstack Dev", "GammaTech",
         40, 60, 13, "Shanghai", "Xuhui", "full_time",
         "3-5年", 3, 5, "本科", "TypeScript", None, None, None,
         None, "互联网", None, None, None, None, None, None,
         "raw jd 3", None, 90.0, None),
        ("https://example.com/job/4", "boss", "ML Engineer", "DeltaAI",
         50, 80, 15, "Shenzhen", "Nanshan", "full_time",
         "5-10年", 5, 10, "硕士", "PyTorch", None, None, None,
         None, "AI", None, None, None, None, None, None,
         "raw jd 4", None, 70.0, None),
        ("https://example.com/job/5", "boss", "Data Analyst", "AlphaCorp",
         15, 35, 13, "Beijing", "Haidian", "full_time",
         "1-3年", 1, 3, "本科", "SQL", None, None, None,
         None, "互联网", None, None, None, None, None, None,
         "raw jd 5", None, 80.0, None),
        ("https://example.com/job/6", "boss", "DevOps Lead", "BetaInc",
         60, 100, 14, "Shanghai", "Jing'an", "full_time",
         "5-10年", 5, 10, "本科", "Kubernetes", None, None, None,
         None, "金融", None, None, None, None, None, None,
         "raw jd 6", None, 65.0, None),
    ]

    insert_sql = """
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
    for job in jobs:
        await db.execute_write(insert_sql, job)

    return db


# Strategy for generating simple letter-only strings for LIKE matching
_letter_text = st.text(
    min_size=1, max_size=5,
    alphabet=st.characters(whitelist_categories=("L",)),
)


# ---------------------------------------------------------------------------
# Property 2a: keyword LIKE 匹配
# ---------------------------------------------------------------------------


class TestKeywordLikePreservation:
    """
    Property 2a: For all keyword values, returned jobs' title SHALL contain
    keyword (case-insensitive LIKE).

    **Validates: Requirements 3.1, 3.2**
    """

    @given(keyword=_letter_text)
    @settings(max_examples=50, deadline=None)
    def test_keyword_like_matching(self, keyword: str):
        async def _check():
            db = await _setup_db_with_jobs()
            try:
                tool = QueryJobsTool()
                result = await tool.execute({"keyword": keyword}, {"db": db})
                assert result["success"] is True
                for job in result["jobs"]:
                    assert keyword.lower() in job["title"].lower(), (
                        f"keyword='{keyword}' but job title='{job['title']}' "
                        f"does not contain keyword (case-insensitive)"
                    )
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Property 2b: city LIKE 匹配
# ---------------------------------------------------------------------------


class TestCityLikePreservation:
    """
    Property 2b: For all city values, returned jobs' city SHALL contain city.

    **Validates: Requirements 3.2**
    """

    @given(city=_letter_text)
    @settings(max_examples=50, deadline=None)
    def test_city_like_matching(self, city: str):
        async def _check():
            db = await _setup_db_with_jobs()
            try:
                tool = QueryJobsTool()
                result = await tool.execute({"city": city}, {"db": db})
                assert result["success"] is True
                for job in result["jobs"]:
                    assert city.lower() in job["city"].lower(), (
                        f"city='{city}' but job city='{job['city']}' "
                        f"does not contain city (case-insensitive)"
                    )
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Property 2c: company LIKE 匹配
# ---------------------------------------------------------------------------


class TestCompanyLikePreservation:
    """
    Property 2c: For all company values, returned jobs' company SHALL contain
    company.

    **Validates: Requirements 3.2**
    """

    @given(company=_letter_text)
    @settings(max_examples=50, deadline=None)
    def test_company_like_matching(self, company: str):
        async def _check():
            db = await _setup_db_with_jobs()
            try:
                tool = QueryJobsTool()
                result = await tool.execute({"company": company}, {"db": db})
                assert result["success"] is True
                for job in result["jobs"]:
                    assert company.lower() in job["company"].lower(), (
                        f"company='{company}' but job company='{job['company']}' "
                        f"does not contain company (case-insensitive)"
                    )
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Property 2d: salary_max 过滤
# ---------------------------------------------------------------------------


class TestSalaryMaxPreservation:
    """
    Property 2d: For all salary_max=M, returned jobs SHALL have salary_min <= M.

    **Validates: Requirements 3.1**
    """

    @given(salary_max=st.integers(min_value=1, max_value=200))
    @settings(max_examples=50, deadline=None)
    def test_salary_max_filtering(self, salary_max: int):
        async def _check():
            db = await _setup_db_with_jobs()
            try:
                tool = QueryJobsTool()
                result = await tool.execute(
                    {"salary_max": salary_max}, {"db": db}
                )
                assert result["success"] is True
                for job in result["jobs"]:
                    assert job["salary_min"] <= salary_max, (
                        f"salary_max={salary_max} but job has "
                        f"salary_min={job['salary_min']} which exceeds the max"
                    )
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Property 2e: limit 上限
# ---------------------------------------------------------------------------


class TestLimitPreservation:
    """
    Property 2e: For all limit=L, returned count SHALL be <= min(L, 50).

    **Validates: Requirements 3.3**
    """

    @given(limit=st.integers(min_value=1, max_value=200))
    @settings(max_examples=50, deadline=None)
    def test_limit_cap(self, limit: int):
        async def _check():
            db = await _setup_db_with_jobs()
            try:
                tool = QueryJobsTool()
                result = await tool.execute({"limit": limit}, {"db": db})
                assert result["success"] is True
                expected_max = min(limit, 50)
                assert result["count"] <= expected_max, (
                    f"limit={limit} → expected at most {expected_max} results, "
                    f"got {result['count']}"
                )
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Property 2f: 返回格式
# ---------------------------------------------------------------------------


class TestResultFormatPreservation:
    """
    Property 2f: Result format SHALL always be
    {"success": bool, "count": int, "jobs": list}.

    **Validates: Requirements 3.4**
    """

    @given(
        keyword=st.one_of(st.none(), _letter_text),
        salary_max=st.one_of(st.none(), st.integers(min_value=1, max_value=200)),
        limit=st.one_of(st.none(), st.integers(min_value=1, max_value=200)),
    )
    @settings(max_examples=50, deadline=None)
    def test_result_format(self, keyword, salary_max, limit):
        async def _check():
            db = await _setup_db_with_jobs()
            try:
                tool = QueryJobsTool()
                params = {}
                if keyword is not None:
                    params["keyword"] = keyword
                if salary_max is not None:
                    params["salary_max"] = salary_max
                if limit is not None:
                    params["limit"] = limit
                result = await tool.execute(params, {"db": db})

                # Check top-level keys
                assert {"success", "count", "jobs"} <= set(result.keys()), (
                    f"Expected at least keys {{'success', 'count', 'jobs'}}, "
                    f"got {set(result.keys())}"
                )
                # 'hint' is allowed when count == 0
                extra = set(result.keys()) - {"success", "count", "jobs", "hint"}
                assert not extra, (
                    f"Unexpected keys: {extra}"
                )
                assert isinstance(result["success"], bool), (
                    f"'success' should be bool, got {type(result['success'])}"
                )
                assert isinstance(result["count"], int), (
                    f"'count' should be int, got {type(result['count'])}"
                )
                assert isinstance(result["jobs"], list), (
                    f"'jobs' should be list, got {type(result['jobs'])}"
                )
                assert result["count"] == len(result["jobs"]), (
                    f"'count' ({result['count']}) != len(jobs) ({len(result['jobs'])})"
                )
            finally:
                await db.close()

        _run_async(_check())
