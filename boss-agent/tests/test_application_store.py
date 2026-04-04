"""application_store 模块单元测试"""

import pytest
import pytest_asyncio

from db.database import Database
from tools.data.application_store import (
    SaveApplicationTool,
    get_application,
    get_applications_by_job,
    update_application_status,
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
async def job_id(db: Database) -> int:
    """插入一条岗位记录，返回其 ID（applications 表的 FK 依赖）。"""
    return await db.execute_write(
        "INSERT INTO jobs (url, title, company) VALUES (?, ?, ?)",
        ("https://example.com/job/1", "AI 工程师", "测试公司"),
    )


@pytest_asyncio.fixture
def tool():
    return SaveApplicationTool()


# ---------------------------------------------------------------------------
# SaveApplicationTool 基础属性
# ---------------------------------------------------------------------------

class TestSaveApplicationToolMeta:
    def test_name(self, tool: SaveApplicationTool):
        assert tool.name == "save_application"

    def test_category(self, tool: SaveApplicationTool):
        assert tool.category == "data"

    def test_not_concurrency_safe(self, tool: SaveApplicationTool):
        assert tool.is_concurrency_safe is False

    def test_job_id_required_in_schema(self, tool: SaveApplicationTool):
        assert "job_id" in tool.parameters_schema["required"]

    def test_schema_has_expected_properties(self, tool: SaveApplicationTool):
        props = tool.parameters_schema["properties"]
        for key in ("job_id", "resume_id", "match_result_id", "greeting",
                     "greeting_strategy", "status", "applied_at", "error_message"):
            assert key in props


# ---------------------------------------------------------------------------
# SaveApplicationTool.execute
# ---------------------------------------------------------------------------

class TestSaveApplicationExecute:
    @pytest.mark.asyncio
    async def test_save_returns_application_id(
        self, db: Database, tool: SaveApplicationTool, job_id: int
    ):
        result = await tool.execute({"job_id": job_id}, {"db": db})
        assert result["application_id"] is not None
        assert result["application_id"] >= 1

    @pytest.mark.asyncio
    async def test_save_with_all_fields(
        self, db: Database, tool: SaveApplicationTool, job_id: int
    ):
        result = await tool.execute(
            {
                "job_id": job_id,
                "greeting": "您好，我对这个岗位很感兴趣",
                "status": "sent",
                "applied_at": "2024-01-15T10:30:00",
                "error_message": None,
            },
            {"db": db},
        )
        app = await get_application(db, result["application_id"])
        assert app is not None
        assert app["job_id"] == job_id
        assert app["greeting"] == "您好，我对这个岗位很感兴趣"
        assert app["status"] == "sent"
        assert app["applied_at"] == "2024-01-15T10:30:00"

    @pytest.mark.asyncio
    async def test_save_defaults_status_to_pending(
        self, db: Database, tool: SaveApplicationTool, job_id: int
    ):
        result = await tool.execute({"job_id": job_id}, {"db": db})
        app = await get_application(db, result["application_id"])
        assert app["status"] == "pending"

    @pytest.mark.asyncio
    async def test_created_at_auto_generated(
        self, db: Database, tool: SaveApplicationTool, job_id: int
    ):
        result = await tool.execute({"job_id": job_id}, {"db": db})
        app = await get_application(db, result["application_id"])
        assert app["created_at"] is not None

    @pytest.mark.asyncio
    async def test_save_with_resume_id(
        self, db: Database, tool: SaveApplicationTool, job_id: int
    ):
        """验证投递记录可关联简历版本"""
        resume_id = await db.execute_write(
            "INSERT INTO resumes (name) VALUES (?)", ("张三",)
        )
        result = await tool.execute(
            {"job_id": job_id, "resume_id": resume_id, "greeting": "你好"},
            {"db": db},
        )
        app = await get_application(db, result["application_id"])
        assert app["resume_id"] == resume_id


# ---------------------------------------------------------------------------
# get_application
# ---------------------------------------------------------------------------

class TestGetApplication:
    @pytest.mark.asyncio
    async def test_get_existing(
        self, db: Database, tool: SaveApplicationTool, job_id: int
    ):
        result = await tool.execute(
            {"job_id": job_id, "greeting": "你好"},
            {"db": db},
        )
        app = await get_application(db, result["application_id"])
        assert app is not None
        assert app["id"] == result["application_id"]
        assert app["greeting"] == "你好"

    @pytest.mark.asyncio
    async def test_get_not_found(self, db: Database):
        app = await get_application(db, 99999)
        assert app is None


# ---------------------------------------------------------------------------
# get_applications_by_job
# ---------------------------------------------------------------------------

class TestGetApplicationsByJob:
    @pytest.mark.asyncio
    async def test_returns_correct_list(
        self, db: Database, tool: SaveApplicationTool, job_id: int
    ):
        ctx = {"db": db}
        await tool.execute({"job_id": job_id, "greeting": "第一次投递"}, ctx)
        await tool.execute({"job_id": job_id, "greeting": "第二次投递"}, ctx)

        apps = await get_applications_by_job(db, job_id)
        assert len(apps) == 2
        assert apps[0]["greeting"] == "第一次投递"
        assert apps[1]["greeting"] == "第二次投递"

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_applications(self, db: Database, job_id: int):
        apps = await get_applications_by_job(db, job_id)
        assert apps == []

    @pytest.mark.asyncio
    async def test_filters_by_job_id(
        self, db: Database, tool: SaveApplicationTool, job_id: int
    ):
        # 创建第二个岗位
        job_id_2 = await db.execute_write(
            "INSERT INTO jobs (url, title) VALUES (?, ?)",
            ("https://example.com/job/2", "后端开发"),
        )
        ctx = {"db": db}
        await tool.execute({"job_id": job_id, "greeting": "岗位1"}, ctx)
        await tool.execute({"job_id": job_id_2, "greeting": "岗位2"}, ctx)

        apps_1 = await get_applications_by_job(db, job_id)
        apps_2 = await get_applications_by_job(db, job_id_2)
        assert len(apps_1) == 1
        assert apps_1[0]["greeting"] == "岗位1"
        assert len(apps_2) == 1
        assert apps_2[0]["greeting"] == "岗位2"


# ---------------------------------------------------------------------------
# update_application_status
# ---------------------------------------------------------------------------

class TestUpdateApplicationStatus:
    @pytest.mark.asyncio
    async def test_update_status_only(
        self, db: Database, tool: SaveApplicationTool, job_id: int
    ):
        result = await tool.execute({"job_id": job_id}, {"db": db})
        app_id = result["application_id"]

        await update_application_status(db, app_id, "sent")
        app = await get_application(db, app_id)
        assert app["status"] == "sent"
        assert app["error_message"] is None

    @pytest.mark.asyncio
    async def test_update_status_with_error(
        self, db: Database, tool: SaveApplicationTool, job_id: int
    ):
        result = await tool.execute({"job_id": job_id}, {"db": db})
        app_id = result["application_id"]

        await update_application_status(db, app_id, "failed", "验证码拦截")
        app = await get_application(db, app_id)
        assert app["status"] == "failed"
        assert app["error_message"] == "验证码拦截"

    @pytest.mark.asyncio
    async def test_update_preserves_other_fields(
        self, db: Database, tool: SaveApplicationTool, job_id: int
    ):
        result = await tool.execute(
            {"job_id": job_id, "greeting": "保持不变"},
            {"db": db},
        )
        app_id = result["application_id"]

        await update_application_status(db, app_id, "sent")
        app = await get_application(db, app_id)
        assert app["greeting"] == "保持不变"
        assert app["job_id"] == job_id
