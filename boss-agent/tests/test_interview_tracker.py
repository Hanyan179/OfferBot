"""interview_tracker 模块单元测试"""

import pytest
import pytest_asyncio

from db.database import Database
from tools.data.interview_tracker import (
    ALL_STAGES,
    VALID_TRANSITIONS,
    GetInterviewFunnelTool,
    UpdateInterviewStatusTool,
    get_interview_status,
    get_stage_history,
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
    """插入一条岗位记录（FK 依赖）。"""
    return await db.execute_write(
        "INSERT INTO jobs (url, title, company) VALUES (?, ?, ?)",
        ("https://example.com/job/1", "AI 工程师", "测试公司"),
    )


@pytest_asyncio.fixture
async def app_id(db: Database, job_id: int) -> int:
    """插入一条投递记录（FK 依赖）。"""
    return await db.execute_write(
        "INSERT INTO applications (job_id, status) VALUES (?, ?)",
        (job_id, "sent"),
    )


@pytest_asyncio.fixture
def update_tool():
    return UpdateInterviewStatusTool()


@pytest_asyncio.fixture
def funnel_tool():
    return GetInterviewFunnelTool()


# ---------------------------------------------------------------------------
# UpdateInterviewStatusTool 元数据
# ---------------------------------------------------------------------------

class TestUpdateInterviewStatusToolMeta:
    def test_name(self, update_tool):
        assert update_tool.name == "update_interview_status"

    def test_category(self, update_tool):
        assert update_tool.category == "data"

    def test_not_concurrency_safe(self, update_tool):
        assert update_tool.is_concurrency_safe is False

    def test_required_params(self, update_tool):
        required = update_tool.parameters_schema["required"]
        assert "application_id" in required
        assert "new_stage" in required

    def test_schema_properties(self, update_tool):
        props = update_tool.parameters_schema["properties"]
        for key in ("application_id", "new_stage", "notes", "interview_time"):
            assert key in props


# ---------------------------------------------------------------------------
# GetInterviewFunnelTool 元数据
# ---------------------------------------------------------------------------

class TestGetInterviewFunnelToolMeta:
    def test_name(self, funnel_tool):
        assert funnel_tool.name == "get_interview_funnel"

    def test_category(self, funnel_tool):
        assert funnel_tool.category == "data"

    def test_concurrency_safe(self, funnel_tool):
        assert funnel_tool.is_concurrency_safe is True

    def test_no_required_params(self, funnel_tool):
        schema = funnel_tool.parameters_schema
        assert schema.get("required") is None or schema.get("required") == []


# ---------------------------------------------------------------------------
# 合法状态转换
# ---------------------------------------------------------------------------

class TestValidTransitions:
    @pytest.mark.asyncio
    async def test_applied_to_viewed(self, db, app_id, update_tool):
        result = await update_tool.execute(
            {"application_id": app_id, "new_stage": "viewed"},
            {"db": db},
        )
        assert result["success"] is True
        assert result["from_stage"] == "applied"
        assert result["to_stage"] == "viewed"

    @pytest.mark.asyncio
    async def test_full_happy_path(self, db, app_id, update_tool):
        """走完完整的面试流程: applied → viewed → replied → ... → offer"""
        ctx = {"db": db}
        stages = [
            "viewed", "replied", "interview_scheduled",
            "round_1", "round_2", "round_3", "hr_round", "offer",
        ]
        prev = "applied"
        for stage in stages:
            result = await update_tool.execute(
                {"application_id": app_id, "new_stage": stage},
                ctx,
            )
            assert result["success"] is True
            assert result["from_stage"] == prev
            assert result["to_stage"] == stage
            prev = stage

    @pytest.mark.asyncio
    async def test_applied_to_rejected(self, db, app_id, update_tool):
        result = await update_tool.execute(
            {"application_id": app_id, "new_stage": "rejected"},
            {"db": db},
        )
        assert result["success"] is True
        assert result["to_stage"] == "rejected"

    @pytest.mark.asyncio
    async def test_applied_to_withdrawn(self, db, app_id, update_tool):
        result = await update_tool.execute(
            {"application_id": app_id, "new_stage": "withdrawn"},
            {"db": db},
        )
        assert result["success"] is True
        assert result["to_stage"] == "withdrawn"

    @pytest.mark.asyncio
    async def test_round2_to_hr_round(self, db, app_id, update_tool):
        """round_2 可以跳过 round_3 直接到 hr_round"""
        ctx = {"db": db}
        for stage in ["viewed", "replied", "interview_scheduled", "round_1", "round_2"]:
            await update_tool.execute(
                {"application_id": app_id, "new_stage": stage}, ctx
            )
        result = await update_tool.execute(
            {"application_id": app_id, "new_stage": "hr_round"}, ctx
        )
        assert result["success"] is True
        assert result["from_stage"] == "round_2"
        assert result["to_stage"] == "hr_round"

    @pytest.mark.asyncio
    async def test_with_notes_and_interview_time(self, db, app_id, update_tool):
        result = await update_tool.execute(
            {
                "application_id": app_id,
                "new_stage": "viewed",
                "notes": "HR 已查看简历",
                "interview_time": "2024-03-01T14:00:00",
            },
            {"db": db},
        )
        assert result["success"] is True
        status = await get_interview_status(db, app_id)
        assert status["notes"] == "HR 已查看简历"
        assert status["interview_time"] == "2024-03-01T14:00:00"


# ---------------------------------------------------------------------------
# 非法状态转换
# ---------------------------------------------------------------------------

class TestInvalidTransitions:
    @pytest.mark.asyncio
    async def test_applied_to_offer_rejected(self, db, app_id, update_tool):
        """applied 不能直接跳到 offer"""
        result = await update_tool.execute(
            {"application_id": app_id, "new_stage": "offer"},
            {"db": db},
        )
        assert result["success"] is False
        assert "非法状态转换" in result["error"]
        assert "applied" in result["error"]
        assert "offer" in result["error"]

    @pytest.mark.asyncio
    async def test_applied_to_round_1_rejected(self, db, app_id, update_tool):
        result = await update_tool.execute(
            {"application_id": app_id, "new_stage": "round_1"},
            {"db": db},
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_viewed_to_interview_scheduled_rejected(self, db, app_id, update_tool):
        """viewed 不能直接跳到 interview_scheduled（需先 replied）"""
        ctx = {"db": db}
        await update_tool.execute(
            {"application_id": app_id, "new_stage": "viewed"}, ctx
        )
        result = await update_tool.execute(
            {"application_id": app_id, "new_stage": "interview_scheduled"}, ctx
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_backward_transition_rejected(self, db, app_id, update_tool):
        """不能回退状态"""
        ctx = {"db": db}
        await update_tool.execute(
            {"application_id": app_id, "new_stage": "viewed"}, ctx
        )
        result = await update_tool.execute(
            {"application_id": app_id, "new_stage": "applied"}, ctx
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# 终态不可转换
# ---------------------------------------------------------------------------

class TestTerminalStates:
    @pytest.mark.asyncio
    async def test_offer_is_terminal(self, db, app_id, update_tool):
        ctx = {"db": db}
        for stage in [
            "viewed", "replied", "interview_scheduled",
            "round_1", "round_2", "hr_round", "offer",
        ]:
            await update_tool.execute(
                {"application_id": app_id, "new_stage": stage}, ctx
            )
        # offer 是终态，任何转换都应失败
        for target in ALL_STAGES:
            result = await update_tool.execute(
                {"application_id": app_id, "new_stage": target}, ctx
            )
            assert result["success"] is False, f"offer → {target} should be rejected"

    @pytest.mark.asyncio
    async def test_rejected_is_terminal(self, db, app_id, update_tool):
        ctx = {"db": db}
        await update_tool.execute(
            {"application_id": app_id, "new_stage": "rejected"}, ctx
        )
        for target in ALL_STAGES:
            result = await update_tool.execute(
                {"application_id": app_id, "new_stage": target}, ctx
            )
            assert result["success"] is False, f"rejected → {target} should be rejected"

    @pytest.mark.asyncio
    async def test_withdrawn_is_terminal(self, db, app_id, update_tool):
        ctx = {"db": db}
        await update_tool.execute(
            {"application_id": app_id, "new_stage": "withdrawn"}, ctx
        )
        for target in ALL_STAGES:
            result = await update_tool.execute(
                {"application_id": app_id, "new_stage": target}, ctx
            )
            assert result["success"] is False, f"withdrawn → {target} should be rejected"


# ---------------------------------------------------------------------------
# Stage log 写入
# ---------------------------------------------------------------------------

class TestStageLog:
    @pytest.mark.asyncio
    async def test_log_written_on_transition(self, db, app_id, update_tool):
        await update_tool.execute(
            {"application_id": app_id, "new_stage": "viewed"},
            {"db": db},
        )
        history = await get_stage_history(db, app_id)
        assert len(history) == 1
        assert history[0]["from_stage"] == "applied"
        assert history[0]["to_stage"] == "viewed"

    @pytest.mark.asyncio
    async def test_multiple_logs(self, db, app_id, update_tool):
        ctx = {"db": db}
        await update_tool.execute(
            {"application_id": app_id, "new_stage": "viewed"}, ctx
        )
        await update_tool.execute(
            {"application_id": app_id, "new_stage": "replied"}, ctx
        )
        history = await get_stage_history(db, app_id)
        assert len(history) == 2
        assert history[0]["from_stage"] == "applied"
        assert history[0]["to_stage"] == "viewed"
        assert history[1]["from_stage"] == "viewed"
        assert history[1]["to_stage"] == "replied"

    @pytest.mark.asyncio
    async def test_log_notes_recorded(self, db, app_id, update_tool):
        await update_tool.execute(
            {
                "application_id": app_id,
                "new_stage": "viewed",
                "notes": "HR 已读",
            },
            {"db": db},
        )
        history = await get_stage_history(db, app_id)
        assert history[0]["notes"] == "HR 已读"

    @pytest.mark.asyncio
    async def test_no_log_on_invalid_transition(self, db, app_id, update_tool):
        """非法转换不应写入日志"""
        await update_tool.execute(
            {"application_id": app_id, "new_stage": "offer"},
            {"db": db},
        )
        history = await get_stage_history(db, app_id)
        assert len(history) == 0


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

class TestHelpers:
    @pytest.mark.asyncio
    async def test_get_interview_status_none(self, db, app_id):
        status = await get_interview_status(db, app_id)
        assert status is None

    @pytest.mark.asyncio
    async def test_get_interview_status_after_update(self, db, app_id, update_tool):
        await update_tool.execute(
            {"application_id": app_id, "new_stage": "viewed"},
            {"db": db},
        )
        status = await get_interview_status(db, app_id)
        assert status is not None
        assert status["stage"] == "viewed"
        assert status["application_id"] == app_id

    @pytest.mark.asyncio
    async def test_timestamps_auto_generated(self, db, app_id, update_tool):
        await update_tool.execute(
            {"application_id": app_id, "new_stage": "viewed"},
            {"db": db},
        )
        status = await get_interview_status(db, app_id)
        assert status["stage_changed_at"] is not None
        assert status["created_at"] is not None

    @pytest.mark.asyncio
    async def test_get_stage_history_empty(self, db, app_id):
        history = await get_stage_history(db, app_id)
        assert history == []


# ---------------------------------------------------------------------------
# 面试漏斗
# ---------------------------------------------------------------------------

class TestInterviewFunnel:
    @pytest.mark.asyncio
    async def test_empty_funnel(self, db, funnel_tool):
        result = await funnel_tool.execute({}, {"db": db})
        assert result["total_applied"] == 0
        assert result["viewed_rate"] == 0.0
        assert result["replied_rate"] == 0.0
        assert result["interview_rate"] == 0.0
        assert result["offer_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_funnel_with_data(self, db, job_id, update_tool, funnel_tool):
        """创建 4 个投递，推进到不同阶段，验证漏斗数据"""
        ctx = {"db": db}

        # 创建 4 个投递
        app_ids = []
        for i in range(4):
            aid = await db.execute_write(
                "INSERT INTO applications (job_id, status) VALUES (?, ?)",
                (job_id, "sent"),
            )
            app_ids.append(aid)

        # app_ids[0]: applied → viewed → replied → interview_scheduled → offer
        for stage in ["viewed", "replied", "interview_scheduled",
                       "round_1", "round_2", "hr_round", "offer"]:
            await update_tool.execute(
                {"application_id": app_ids[0], "new_stage": stage}, ctx
            )

        # app_ids[1]: applied → viewed → replied
        for stage in ["viewed", "replied"]:
            await update_tool.execute(
                {"application_id": app_ids[1], "new_stage": stage}, ctx
            )

        # app_ids[2]: applied → viewed
        await update_tool.execute(
            {"application_id": app_ids[2], "new_stage": "viewed"}, ctx
        )

        # app_ids[3]: stays at applied (no transitions)

        result = await funnel_tool.execute({}, ctx)

        assert result["total_applied"] == 4
        assert result["stage_counts"]["applied"] == 4
        assert result["stage_counts"]["viewed"] == 3   # app 0, 1, 2
        assert result["stage_counts"]["replied"] == 2   # app 0, 1
        assert result["stage_counts"]["offer"] == 1     # app 0

        # viewed_rate = 3/4
        assert result["viewed_rate"] == pytest.approx(3 / 4)
        # replied_rate = 2/3
        assert result["replied_rate"] == pytest.approx(2 / 3)
        # interview_rate = 1/2
        assert result["interview_rate"] == pytest.approx(1 / 2)
        # offer_rate = 1/1
        assert result["offer_rate"] == pytest.approx(1 / 1)

    @pytest.mark.asyncio
    async def test_funnel_stage_counts_include_rejected(
        self, db, job_id, update_tool, funnel_tool
    ):
        ctx = {"db": db}
        aid = await db.execute_write(
            "INSERT INTO applications (job_id, status) VALUES (?, ?)",
            (job_id, "sent"),
        )
        await update_tool.execute(
            {"application_id": aid, "new_stage": "rejected"}, ctx
        )
        result = await funnel_tool.execute({}, ctx)
        assert result["stage_counts"]["rejected"] == 1
