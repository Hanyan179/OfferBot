"""
Integration tests for QueryJobsTool and system_prompt.

End-to-end tests verifying:
- Full parameter combination (keyword + city + salary_min + education) returns results satisfying ALL conditions
- build_full_system_prompt() output contains profile guidance section with education/experience keywords
- No-profile scenario: query_jobs works normally without profile-related params
- Multi-condition combination: all filter params stacked correctly

Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5
"""

from __future__ import annotations

import asyncio

from db.database import Database
from tools.data.query_jobs import QueryJobsTool
from agent.system_prompt import build_full_system_prompt

EXPECTED_KEYS = {
    "id", "url", "title", "company", "salary_min", "salary_max",
    "salary_months", "city", "experience", "education", "match_score",
    "has_jd",
}

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


def _run_async(coro):
    """Helper to run async code in sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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
    return (
        url, "boss", title, company,
        salary_min, salary_max, salary_months, city, "浦东", "full_time",
        experience, 1, 3, education,
        "Python", None, None, None,
        None, company_industry, None, None,
        None, None, None, None,
        "raw jd", None, match_score, None,
    )


async def _setup_db_with_jobs(jobs_data: list[tuple]) -> Database:
    db = Database(":memory:")
    await db.connect()
    await db.init_schema()
    for job in jobs_data:
        await db.execute_write(INSERT_SQL, job)
    return db


# ---------------------------------------------------------------------------
# Test 1: End-to-End — keyword + city + salary_min + education (Req 2.1, 2.2, 2.3)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """Full parameter combination: keyword='AI' + city='上海' + salary_min=30 + education='本科'."""

    def test_all_conditions_satisfied(self):
        async def _check():
            jobs = [
                # Should match: title has AI, city 上海, salary_min=35>=30, education 本科
                _make_job("https://j/1", title="AI工程师", city="上海", salary_min=35, salary_max=60, education="本科"),
                # Should NOT match: salary_min=20 < 30
                _make_job("https://j/2", title="AI算法", city="上海", salary_min=20, salary_max=50, education="本科"),
                # Should NOT match: education 硕士 != 本科
                _make_job("https://j/3", title="AI架构师", city="上海", salary_min=40, salary_max=70, education="硕士"),
                # Should NOT match: city 北京 not 上海
                _make_job("https://j/4", title="AI产品", city="北京", salary_min=35, salary_max=55, education="本科"),
                # Should NOT match: title has no AI
                _make_job("https://j/5", title="后端工程师", city="上海", salary_min=35, salary_max=55, education="本科"),
                # Should match: all conditions met
                _make_job("https://j/6", title="AI研发", city="上海", salary_min=30, salary_max=50, education="本科"),
            ]
            db = await _setup_db_with_jobs(jobs)
            try:
                result = await QueryJobsTool().execute(
                    {"keyword": "AI", "city": "上海", "salary_min": 30, "education": "本科"},
                    {"db": db},
                )
                assert result["success"] is True
                assert result["count"] == 2, f"Expected 2 matching jobs, got {result['count']}"

                for job in result["jobs"]:
                    # Verify all conditions simultaneously
                    assert "AI" in job["title"], f"Title '{job['title']}' should contain 'AI'"
                    assert "上海" in job["city"], f"City '{job['city']}' should contain '上海'"
                    assert job["salary_min"] >= 30, f"salary_min {job['salary_min']} should be >= 30"
                    assert job["education"] == "本科", f"education '{job['education']}' should be '本科'"

                    # Verify exactly 11 return fields
                    actual_keys = set(job.keys())
                    assert actual_keys == EXPECTED_KEYS, (
                        f"Expected {EXPECTED_KEYS}, got {actual_keys}"
                    )
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Test 2: System Prompt Profile Guidance (Req 2.4)
# ---------------------------------------------------------------------------


class TestSystemPromptProfileGuidance:
    """build_full_system_prompt() should contain profile guidance keywords."""

    def test_prompt_contains_profile_guidance(self):
        prompt = build_full_system_prompt()
        assert "岗位查询策略" in prompt, "Prompt should contain '岗位查询策略' section"
        assert "get_user_profile" in prompt, "Prompt should mention 'get_user_profile'"
        assert "education" in prompt, "Prompt should mention 'education'"
        assert "experience" in prompt, "Prompt should mention 'experience'"


# ---------------------------------------------------------------------------
# Test 3: No-Profile Scenario (Req 3.5)
# ---------------------------------------------------------------------------


class TestNoProfileScenario:
    """Query without profile-related params should return normally."""

    def test_query_without_profile_params(self):
        async def _check():
            jobs = [
                _make_job("https://j/1", title="前端工程师", city="上海"),
                _make_job("https://j/2", title="后端工程师", city="北京"),
            ]
            db = await _setup_db_with_jobs(jobs)
            try:
                # Query with only keyword — no education/experience/company_industry
                result = await QueryJobsTool().execute(
                    {"keyword": "前端"}, {"db": db},
                )
                assert result["success"] is True
                assert result["count"] == 1
                assert result["jobs"][0]["title"] == "前端工程师"

                # Query with only city
                result2 = await QueryJobsTool().execute(
                    {"city": "北京"}, {"db": db},
                )
                assert result2["success"] is True
                assert result2["count"] == 1
                assert result2["jobs"][0]["city"] == "北京"

                # Query with no params at all
                result3 = await QueryJobsTool().execute({}, {"db": db})
                assert result3["success"] is True
                assert result3["count"] == 2
            finally:
                await db.close()

        _run_async(_check())


# ---------------------------------------------------------------------------
# Test 4: Multi-Condition Combination (Req 2.1, 2.2, 2.3, 3.1, 3.2, 3.3)
# ---------------------------------------------------------------------------


class TestMultiConditionCombination:
    """All params stacked: salary_min + salary_max + keyword + city + education + experience + company_industry + limit."""

    def test_all_filters_stacked(self):
        async def _check():
            jobs = [
                # Match all conditions
                _make_job("https://j/1", title="Python开发", city="北京", salary_min=25, salary_max=45,
                          education="硕士", experience="3-5年", company_industry="互联网"),
                # Match all conditions
                _make_job("https://j/2", title="Python架构师", city="北京", salary_min=30, salary_max=50,
                          education="硕士", experience="3-5年", company_industry="互联网"),
                # Fail: salary_min=15 < 20
                _make_job("https://j/3", title="Python工程师", city="北京", salary_min=15, salary_max=40,
                          education="硕士", experience="3-5年", company_industry="互联网"),
                # Fail: salary_min=55 > salary_max filter 50
                _make_job("https://j/4", title="Python专家", city="北京", salary_min=55, salary_max=80,
                          education="硕士", experience="3-5年", company_industry="互联网"),
                # Fail: city 上海 != 北京
                _make_job("https://j/5", title="Python开发", city="上海", salary_min=25, salary_max=45,
                          education="硕士", experience="3-5年", company_industry="互联网"),
                # Fail: education 本科 != 硕士
                _make_job("https://j/6", title="Python开发", city="北京", salary_min=25, salary_max=45,
                          education="本科", experience="3-5年", company_industry="互联网"),
                # Fail: experience 5-10年 doesn't match 3-5年
                _make_job("https://j/7", title="Python开发", city="北京", salary_min=25, salary_max=45,
                          education="硕士", experience="5-10年", company_industry="互联网"),
                # Fail: company_industry 金融 != 互联网
                _make_job("https://j/8", title="Python开发", city="北京", salary_min=25, salary_max=45,
                          education="硕士", experience="3-5年", company_industry="金融"),
                # Fail: title has no Python
                _make_job("https://j/9", title="Java开发", city="北京", salary_min=25, salary_max=45,
                          education="硕士", experience="3-5年", company_industry="互联网"),
            ]
            db = await _setup_db_with_jobs(jobs)
            try:
                result = await QueryJobsTool().execute(
                    {
                        "salary_min": 20,
                        "salary_max": 50,
                        "keyword": "Python",
                        "city": "北京",
                        "education": "硕士",
                        "experience": "3-5年",
                        "company_industry": "互联网",
                        "limit": 5,
                    },
                    {"db": db},
                )
                assert result["success"] is True
                assert result["count"] == 2, f"Expected 2 matching jobs, got {result['count']}"

                for job in result["jobs"]:
                    assert "Python" in job["title"]
                    assert "北京" in job["city"]
                    assert job["salary_min"] >= 20
                    assert job["salary_min"] <= 50  # salary_max filter: salary_min <= 50
                    assert job["education"] == "硕士"

                    # Verify exactly 11 return fields
                    actual_keys = set(job.keys())
                    assert actual_keys == EXPECTED_KEYS
            finally:
                await db.close()

        _run_async(_check())
