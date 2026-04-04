"""job_store 模块单元测试"""

import pytest
import pytest_asyncio

from db.database import Database
from tools.data.job_store import (
    SaveJobTool,
    get_job_by_id,
    get_job_by_url,
    query_jobs,
    update_match_score,
    update_structured_jd,
)


@pytest_asyncio.fixture
async def db(tmp_path):
    """提供一个已初始化 schema 的临时数据库。"""
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()


@pytest_asyncio.fixture
def tool():
    return SaveJobTool()


# ---------------------------------------------------------------------------
# SaveJobTool 基础属性
# ---------------------------------------------------------------------------

class TestSaveJobToolMeta:
    def test_name(self, tool: SaveJobTool):
        assert tool.name == "save_job"

    def test_category(self, tool: SaveJobTool):
        assert tool.category == "data"

    def test_not_concurrency_safe(self, tool: SaveJobTool):
        assert tool.is_concurrency_safe is False

    def test_url_required_in_schema(self, tool: SaveJobTool):
        assert "url" in tool.parameters_schema["required"]


# ---------------------------------------------------------------------------
# SaveJobTool.execute
# ---------------------------------------------------------------------------

class TestSaveJobExecute:
    @pytest.mark.asyncio
    async def test_save_returns_job_id(self, db: Database, tool: SaveJobTool):
        result = await tool.execute(
            {"url": "https://www.zhipin.com/job/1", "title": "AI 工程师", "city": "上海"},
            {"db": db},
        )
        assert result["job_id"] is not None
        assert result["job_id"] >= 1
        assert result["inserted"] is True

    @pytest.mark.asyncio
    async def test_duplicate_url_ignored(self, db: Database, tool: SaveJobTool):
        ctx = {"db": db}
        r1 = await tool.execute({"url": "https://www.zhipin.com/job/dup"}, ctx)
        r2 = await tool.execute({"url": "https://www.zhipin.com/job/dup"}, ctx)

        assert r1["inserted"] is True
        assert r2["inserted"] is False
        # 第二次返回已有记录的 id
        assert r2["job_id"] == r1["job_id"]

        # 数据库中只有一条记录
        rows = await db.execute("SELECT count(*) AS cnt FROM jobs WHERE url = ?", ("https://www.zhipin.com/job/dup",))
        assert rows[0]["cnt"] == 1

    @pytest.mark.asyncio
    async def test_save_with_all_fields(self, db: Database, tool: SaveJobTool):
        params = {
            "url": "https://www.zhipin.com/job/full",
            "platform": "boss",
            "title": "后端开发",
            "company": "字节跳动",
            "salary_min": 25,
            "salary_max": 50,
            "salary_months": 15,
            "city": "北京",
            "district": "海淀区",
            "work_type": "full_time",
            "experience": "3-5年",
            "experience_min": 3,
            "experience_max": 5,
            "education": "本科",
            "skills": '["Python", "Go"]',
            "skills_must": '["Python"]',
            "skills_preferred": '["Go", "K8s"]',
            "responsibilities": '["系统设计"]',
            "company_size": "10000人以上",
            "company_industry": "互联网",
            "company_stage": "上市",
            "company_description": "全球领先的科技公司",
            "recruiter_name": "张三",
            "recruiter_title": "HR",
            "benefits": '["五险一金"]',
            "tags": '["急招"]',
            "raw_jd": "岗位描述原文",
        }
        result = await tool.execute(params, {"db": db})
        job = await get_job_by_id(db, result["job_id"])
        assert job is not None
        # 验证所有可写字段
        assert job["url"] == "https://www.zhipin.com/job/full"
        assert job["platform"] == "boss"
        assert job["title"] == "后端开发"
        assert job["company"] == "字节跳动"
        assert job["salary_min"] == 25
        assert job["salary_max"] == 50
        assert job["salary_months"] == 15
        assert job["city"] == "北京"
        assert job["district"] == "海淀区"
        assert job["work_type"] == "full_time"
        assert job["experience"] == "3-5年"
        assert job["experience_min"] == 3
        assert job["experience_max"] == 5
        assert job["education"] == "本科"
        assert job["skills"] == '["Python", "Go"]'
        assert job["skills_must"] == '["Python"]'
        assert job["skills_preferred"] == '["Go", "K8s"]'
        assert job["responsibilities"] == '["系统设计"]'
        assert job["company_size"] == "10000人以上"
        assert job["company_industry"] == "互联网"
        assert job["company_stage"] == "上市"
        assert job["company_description"] == "全球领先的科技公司"
        assert job["recruiter_name"] == "张三"
        assert job["recruiter_title"] == "HR"
        assert job["benefits"] == '["五险一金"]'
        assert job["tags"] == '["急招"]'
        assert job["raw_jd"] == "岗位描述原文"
        # 自动生成的时间戳
        assert job["discovered_at"] is not None
        assert job["updated_at"] is not None
        # 尚未解析/匹配
        assert job["parsed_at"] is None
        assert job["match_score"] is None
        assert job["structured_jd"] is None


# ---------------------------------------------------------------------------
# query_jobs
# ---------------------------------------------------------------------------

class TestQueryJobs:
    @pytest.mark.asyncio
    async def test_query_no_filters(self, db: Database, tool: SaveJobTool):
        ctx = {"db": db}
        await tool.execute({"url": "https://a.com/1", "city": "上海", "title": "AI"}, ctx)
        await tool.execute({"url": "https://a.com/2", "city": "北京", "title": "后端"}, ctx)

        jobs = await query_jobs(db)
        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_query_by_city(self, db: Database, tool: SaveJobTool):
        ctx = {"db": db}
        await tool.execute({"url": "https://a.com/1", "city": "上海"}, ctx)
        await tool.execute({"url": "https://a.com/2", "city": "北京"}, ctx)

        jobs = await query_jobs(db, {"city": "上海"})
        assert len(jobs) == 1
        assert jobs[0]["city"] == "上海"

    @pytest.mark.asyncio
    async def test_query_by_keyword(self, db: Database, tool: SaveJobTool):
        ctx = {"db": db}
        await tool.execute({"url": "https://a.com/1", "title": "AI 工程师"}, ctx)
        await tool.execute({"url": "https://a.com/2", "title": "后端开发"}, ctx)

        jobs = await query_jobs(db, {"keyword": "AI"})
        assert len(jobs) == 1
        assert "AI" in jobs[0]["title"]

    @pytest.mark.asyncio
    async def test_query_by_min_match_score(self, db: Database, tool: SaveJobTool):
        ctx = {"db": db}
        r1 = await tool.execute({"url": "https://a.com/1"}, ctx)
        r2 = await tool.execute({"url": "https://a.com/2"}, ctx)
        await update_match_score(db, r1["job_id"], 90.0, "高匹配")
        await update_match_score(db, r2["job_id"], 60.0, "低匹配")

        jobs = await query_jobs(db, {"min_match_score": 80.0})
        assert len(jobs) == 1
        assert jobs[0]["match_score"] == 90.0

    @pytest.mark.asyncio
    async def test_query_by_company(self, db: Database, tool: SaveJobTool):
        ctx = {"db": db}
        await tool.execute({"url": "https://a.com/1", "company": "字节跳动"}, ctx)
        await tool.execute({"url": "https://a.com/2", "company": "阿里巴巴"}, ctx)

        jobs = await query_jobs(db, {"company": "字节跳动"})
        assert len(jobs) == 1
        assert jobs[0]["company"] == "字节跳动"

    @pytest.mark.asyncio
    async def test_query_combined_filters(self, db: Database, tool: SaveJobTool):
        ctx = {"db": db}
        r1 = await tool.execute({"url": "https://a.com/1", "city": "上海", "title": "AI 工程师"}, ctx)
        await tool.execute({"url": "https://a.com/2", "city": "上海", "title": "后端开发"}, ctx)
        await tool.execute({"url": "https://a.com/3", "city": "北京", "title": "AI 研究员"}, ctx)

        jobs = await query_jobs(db, {"city": "上海", "keyword": "AI"})
        assert len(jobs) == 1
        assert jobs[0]["city"] == "上海"
        assert "AI" in jobs[0]["title"]


# ---------------------------------------------------------------------------
# update_match_score / update_structured_jd
# ---------------------------------------------------------------------------

class TestUpdateFunctions:
    @pytest.mark.asyncio
    async def test_update_match_score(self, db: Database, tool: SaveJobTool):
        r = await tool.execute({"url": "https://a.com/match"}, {"db": db})
        await update_match_score(db, r["job_id"], 85.5, '{"skill": 90}')

        job = await get_job_by_id(db, r["job_id"])
        assert job["match_score"] == 85.5
        assert job["match_detail"] == '{"skill": 90}'

    @pytest.mark.asyncio
    async def test_update_structured_jd(self, db: Database, tool: SaveJobTool):
        r = await tool.execute({"url": "https://a.com/jd"}, {"db": db})
        jd_json = '{"title": "AI 工程师", "skills": ["Python"]}'
        await update_structured_jd(db, r["job_id"], jd_json)

        job = await get_job_by_id(db, r["job_id"])
        assert job["structured_jd"] == jd_json
        assert job["parsed_at"] is not None


# ---------------------------------------------------------------------------
# get_job_by_url / get_job_by_id
# ---------------------------------------------------------------------------

class TestGetJobHelpers:
    @pytest.mark.asyncio
    async def test_get_by_url_found(self, db: Database, tool: SaveJobTool):
        url = "https://a.com/byurl"
        await tool.execute({"url": url, "title": "测试岗位"}, {"db": db})

        job = await get_job_by_url(db, url)
        assert job is not None
        assert job["url"] == url
        assert job["title"] == "测试岗位"

    @pytest.mark.asyncio
    async def test_get_by_url_not_found(self, db: Database):
        job = await get_job_by_url(db, "https://nonexistent.com")
        assert job is None

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, db: Database, tool: SaveJobTool):
        r = await tool.execute({"url": "https://a.com/byid"}, {"db": db})
        job = await get_job_by_id(db, r["job_id"])
        assert job is not None
        assert job["id"] == r["job_id"]

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db: Database):
        job = await get_job_by_id(db, 99999)
        assert job is None
