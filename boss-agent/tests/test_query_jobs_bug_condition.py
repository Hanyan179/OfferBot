"""
Property-based tests for QueryJobsTool bug conditions.

These tests encode the EXPECTED (correct) behavior. They are designed to
FAIL on the current unfixed code, confirming the bugs exist.

Property 1a: salary_min 过滤正确性
  For all salary_min=N (1-100), every returned job SHALL have job["salary_min"] >= N.
  **Validates: Requirements 1.1**

Property 1b: 返回字段精简
  For any query call, returned job dicts SHALL only contain keys
  {id, url, title, company, salary_min, salary_max, salary_months, city,
   experience, education, match_score} — exactly 11 fields.
  **Validates: Requirements 1.2**

Property 1c: education 参数可用
  When education="本科" is passed, returned jobs SHALL all have education=="本科".
  **Validates: Requirements 1.3**
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings, strategies as st

from db.database import Database
from tools.data.query_jobs import QueryJobsTool

EXPECTED_KEYS = {
    "id", "url", "title", "company", "salary_min", "salary_max",
    "salary_months", "city", "experience", "education", "match_score",
    "has_jd",
}


def _run_async(coro):
    """Helper to run async code in hypothesis tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _setup_db_with_jobs() -> Database:
    """Create an in-memory DB, init schema, and insert test jobs."""
    db = Database(":memory:")
    await db.connect()
    await db.init_schema()

    # Insert jobs with varied salary_min, salary_max, education values.
    # These are carefully chosen to expose the salary_min filtering bug:
    #   - Job A: salary_min=10, salary_max=30  (low range)
    #   - Job B: salary_min=20, salary_max=50  (mid range, salary_max high)
    #   - Job C: salary_min=40, salary_max=60  (high range)
    #   - Job D: salary_min=50, salary_max=80  (higher range)
    # When querying salary_min=40, only C and D should be returned.
    # But the buggy code uses salary_max >= 40, so B (salary_max=50) also passes.
    jobs = [
        ("https://example.com/job/1", "boss", "AI工程师", "公司A",
         10, 30, 13, "上海", "浦东", "full_time",
         "1-3年", 1, 3, "本科", "Python", None, None, None,
         None, None, None, None, None, None, None, None,
         "raw jd 1", None, 85.0, None),
        ("https://example.com/job/2", "boss", "后端开发", "公司B",
         20, 50, 14, "北京", "朝阳", "full_time",
         "3-5年", 3, 5, "硕士", "Java", None, None, None,
         None, None, None, None, None, None, None, None,
         "raw jd 2", None, 75.0, None),
        ("https://example.com/job/3", "boss", "全栈工程师", "公司C",
         40, 60, 13, "上海", "徐汇", "full_time",
         "3-5年", 3, 5, "本科", "TypeScript", None, None, None,
         None, None, None, None, None, None, None, None,
         "raw jd 3", None, 90.0, None),
        ("https://example.com/job/4", "boss", "算法工程师", "公司D",
         50, 80, 15, "深圳", "南山", "full_time",
         "5-10年", 5, 10, "硕士", "PyTorch", None, None, None,
         None, None, None, None, None, None, None, None,
         "raw jd 4", None, 70.0, None),
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


# ---------------------------------------------------------------------------
# Property 1a: salary_min 过滤正确性
# ---------------------------------------------------------------------------


class TestSalaryMinFiltering:
    """
    Property 1a: For all salary_min=N (1-100), every returned job SHALL have
    job["salary_min"] >= N.

    **Validates: Requirements 1.1**

    The buggy code uses `salary_max >= ?` instead of `salary_min >= ?`,
    so a job with salary_min=20, salary_max=50 will be returned when
    querying salary_min=40 (because 50 >= 40), even though salary_min=20 < 40.
    """

    @given(salary_min=st.integers(min_value=1, max_value=100))
    @settings(max_examples=50, deadline=None)
    def test_salary_min_filtering(self, salary_min: int):
        async def _check():
            db = await _setup_db_with_jobs()
            try:
                tool = QueryJobsTool()
                result = await tool.execute(
                    {"salary_min": salary_min}, {"db": db}
                )
                assert result["success"] is True
                for job in result["jobs"]:
                    assert job["salary_min"] >= salary_min, (
                        f"salary_min={salary_min} query returned job with "
                        f"salary_min={job['salary_min']}, salary_max={job['salary_max']}. "
                        f"Bug: salary_max >= {salary_min} passed but salary_min < {salary_min}"
                    )
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Property 1b: 返回字段精简
# ---------------------------------------------------------------------------


class TestReturnFieldsCount:
    """
    Property 1b: For any query call, returned job dicts SHALL only contain
    keys {id, url, title, company, salary_min, salary_max, salary_months,
    city, experience, education, match_score, has_jd} — exactly 12 fields.

    **Validates: Requirements 1.2**

    The buggy code returns 17 fields including raw_jd, recruiter_name,
    recruiter_title, company_size, company_industry, discovered_at.
    """

    def test_return_fields_are_exactly_11(self):
        async def _check():
            db = await _setup_db_with_jobs()
            try:
                tool = QueryJobsTool()
                result = await tool.execute({}, {"db": db})
                assert result["success"] is True
                assert result["count"] > 0, "Need at least one job to check fields"
                for job in result["jobs"]:
                    actual_keys = set(job.keys())
                    assert actual_keys == EXPECTED_KEYS, (
                        f"Expected {len(EXPECTED_KEYS)} fields {EXPECTED_KEYS}, "
                        f"got {len(actual_keys)} fields {actual_keys}. "
                        f"Extra fields: {actual_keys - EXPECTED_KEYS}"
                    )
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Property 1c: education 参数可用
# ---------------------------------------------------------------------------


class TestEducationFiltering:
    """
    Property 1c: When education="本科" is passed, returned jobs SHALL all
    have education=="本科".

    **Validates: Requirements 1.3**

    The buggy code's parameters_schema does not include education, so the
    parameter is silently ignored and jobs with all education values are returned.
    """

    def test_education_filter_applied(self):
        async def _check():
            db = await _setup_db_with_jobs()
            try:
                tool = QueryJobsTool()
                # Pass education="本科" — buggy code ignores this param
                result = await tool.execute(
                    {"education": "本科"}, {"db": db}
                )
                assert result["success"] is True
                # We inserted 2 本科 jobs and 2 硕士 jobs.
                # If education filter works, only 2 jobs should be returned.
                # If ignored, all 4 jobs are returned.
                assert result["count"] > 0, "Should have at least one 本科 job"
                for job in result["jobs"]:
                    assert job["education"] == "本科", (
                        f"education='本科' filter passed but got job with "
                        f"education='{job['education']}'. "
                        f"Bug: education parameter is ignored by query_jobs"
                    )
            finally:
                await db.close()

        _run_async(_check())
