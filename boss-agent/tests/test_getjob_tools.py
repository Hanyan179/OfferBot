"""
getjob Tool 层单元测试

覆盖 10 个 getjob tools + GetjobServiceManagerTool:
- PlatformStatusTool
- PlatformStartTaskTool / PlatformStopTaskTool
- PlatformGetConfigTool / PlatformUpdateConfigTool
- SyncJobsTool (含 parse_salary / format_salary)
- FetchJobDetailTool
- PlatformDeliverTool
- PlatformStatsTool
- GetjobServiceManagerTool
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from db.database import Database
from tools.getjob.platform_status import PlatformStatusTool
from tools.getjob.platform_control import PlatformStartTaskTool, PlatformStopTaskTool
from tools.getjob.platform_config import PlatformGetConfigTool, PlatformUpdateConfigTool
from tools.getjob.platform_sync import SyncJobsTool, parse_salary, format_salary
from tools.getjob.platform_stats import PlatformStatsTool
from tools.getjob.platform_deliver import PlatformDeliverTool
from tools.getjob.fetch_detail import FetchJobDetailTool
from tools.getjob.service_manager import GetjobServiceManagerTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path):
    """临时 SQLite 数据库，已初始化 schema。"""
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()


@pytest.fixture
def mock_client():
    """AsyncMock GetjobClient。"""
    return AsyncMock()


def _ctx(client=None, db=None, **extras):
    """构建 context dict。"""
    ctx = {"getjob_client": client or AsyncMock(), "db": db or AsyncMock()}
    ctx.update(extras)
    return ctx


def _ok(data=None):
    return {"success": True, "data": data or {}, "error": None}


def _err(error="some error"):
    return {"success": False, "data": None, "error": error}


def _conn_refused():
    return {"success": False, "data": None, "error": "无法连接 getjob 服务 (http://localhost:8888)"}


# ---------------------------------------------------------------------------
# 5.1 — parse_salary / format_salary helpers
# ---------------------------------------------------------------------------

class TestParseSalary:
    def test_range(self):
        assert parse_salary("25-50K") == (25, 50, None)

    def test_range_with_k_prefix(self):
        assert parse_salary("25K-50K") == (25, 50, None)

    def test_range_with_months(self):
        assert parse_salary("25-50K·14薪") == (25, 50, 14)

    def test_negotiable(self):
        assert parse_salary("面议") == (None, None, None)

    def test_none_input(self):
        assert parse_salary(None) == (None, None, None)

    def test_empty_string(self):
        assert parse_salary("") == (None, None, None)

    def test_single_k(self):
        assert parse_salary("30K") == (30, 30, None)

    def test_format_round_trip(self):
        s = format_salary(25, 50)
        mn, mx, months = parse_salary(s)
        assert (mn, mx) == (25, 50)


# ---------------------------------------------------------------------------
# 5.2 — PlatformStatusTool
# ---------------------------------------------------------------------------

class TestPlatformStatusTool:
    @pytest.mark.asyncio
    async def test_valid_platform_success(self, mock_client):
        mock_client.get_status.return_value = _ok({"isRunning": False, "isLoggedIn": True})
        tool = PlatformStatusTool()
        result = await tool.execute({"platform": "liepin"}, _ctx(mock_client))
        assert result["success"] is True
        assert result["data"]["isLoggedIn"] is True
        mock_client.get_status.assert_awaited_once_with("liepin")

    @pytest.mark.asyncio
    async def test_invalid_platform_error(self):
        tool = PlatformStatusTool()
        result = await tool.execute({"platform": "boss"}, _ctx())
        assert result["success"] is False
        assert "不支持" in result["error"]

    @pytest.mark.asyncio
    async def test_connection_refused_service_down(self, mock_client):
        mock_client.get_status.return_value = _conn_refused()
        tool = PlatformStatusTool()
        result = await tool.execute({"platform": "liepin"}, _ctx(mock_client))
        assert result["success"] is False
        assert "getjob 服务未启动" in result["error"]

    @pytest.mark.asyncio
    async def test_zhilian_platform(self, mock_client):
        mock_client.get_status.return_value = _ok({"isRunning": True})
        tool = PlatformStatusTool()
        result = await tool.execute({"platform": "zhilian"}, _ctx(mock_client))
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 5.3 — PlatformStartTaskTool
# ---------------------------------------------------------------------------

class TestPlatformStartTaskTool:
    @pytest.mark.asyncio
    async def test_returns_confirm_required_card(self):
        tool = PlatformStartTaskTool()
        result = await tool.execute(
            {"platform": "liepin", "keywords": "AI Agent", "city": "上海"},
            _ctx(),
        )
        assert result["action"] == "confirm_required"
        assert result["card_type"] == "start_task"
        assert result["status"] == "pending"
        # fields 应包含 keywords, city 等
        field_ids = [f["id"] for f in result["fields"]]
        assert "keywords" in field_ids
        assert "city" in field_ids
        assert "salaryCode" in field_ids

    @pytest.mark.asyncio
    async def test_card_fields_carry_params(self):
        tool = PlatformStartTaskTool()
        result = await tool.execute(
            {"platform": "liepin", "keywords": "全栈", "maxPages": 5},
            _ctx(),
        )
        fields_map = {f["id"]: f["value"] for f in result["fields"]}
        assert fields_map["keywords"] == "全栈"
        assert fields_map["maxPages"] == 5

    @pytest.mark.asyncio
    async def test_invalid_platform_error(self):
        tool = PlatformStartTaskTool()
        result = await tool.execute({"platform": "boss"}, _ctx())
        assert result["success"] is False
        assert "不支持" in result["error"]


# ---------------------------------------------------------------------------
# 5.4 — PlatformStopTaskTool
# ---------------------------------------------------------------------------

class TestPlatformStopTaskTool:
    @pytest.mark.asyncio
    async def test_stop_delegates_to_client(self, mock_client):
        mock_client.stop_task.return_value = _ok({"status": "stopped"})
        tool = PlatformStopTaskTool()
        result = await tool.execute({"platform": "liepin"}, _ctx(mock_client))
        assert result["success"] is True
        mock_client.stop_task.assert_awaited_once_with("liepin")

    @pytest.mark.asyncio
    async def test_no_running_task(self, mock_client):
        mock_client.stop_task.return_value = _err("没有正在运行的任务")
        tool = PlatformStopTaskTool()
        result = await tool.execute({"platform": "liepin"}, _ctx(mock_client))
        assert result["success"] is True
        assert "没有运行中" in result["message"]

    @pytest.mark.asyncio
    async def test_invalid_platform(self):
        tool = PlatformStopTaskTool()
        result = await tool.execute({"platform": "invalid"}, _ctx())
        assert result["success"] is False


# ---------------------------------------------------------------------------
# 5.5 — PlatformGetConfigTool
# ---------------------------------------------------------------------------

class TestPlatformGetConfigTool:
    @pytest.mark.asyncio
    async def test_returns_config_data(self, mock_client):
        mock_client.get_config.return_value = _ok({"keywords": "AI", "scrapeOnly": True})
        tool = PlatformGetConfigTool()
        result = await tool.execute({"platform": "liepin"}, _ctx(mock_client))
        assert result["success"] is True
        assert result["data"]["keywords"] == "AI"

    @pytest.mark.asyncio
    async def test_connection_refused(self, mock_client):
        mock_client.get_config.return_value = _conn_refused()
        tool = PlatformGetConfigTool()
        result = await tool.execute({"platform": "liepin"}, _ctx(mock_client))
        assert result["success"] is False
        assert "getjob 服务未启动" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_platform(self):
        tool = PlatformGetConfigTool()
        result = await tool.execute({"platform": "nope"}, _ctx())
        assert result["success"] is False


# ---------------------------------------------------------------------------
# 5.6 — PlatformUpdateConfigTool
# ---------------------------------------------------------------------------

class TestPlatformUpdateConfigTool:
    @pytest.mark.asyncio
    async def test_monthly_salary_min_auto_conversion(self, mock_client):
        """monthly_salary_min=30 → 年薪36万 → salaryCode='5' (30-50万)"""
        mock_client.update_config.return_value = _ok({"updated": True})
        tool = PlatformUpdateConfigTool()
        result = await tool.execute(
            {"platform": "liepin", "config": {"monthly_salary_min": 30}},
            _ctx(mock_client),
        )
        assert result["success"] is True
        # 验证传给 client 的 config 包含 salaryCode
        call_args = mock_client.update_config.call_args
        sent_config = call_args[0][1]  # positional arg: (platform, config)
        assert sent_config["salaryCode"] == "5"
        # 验证返回的 salary_conversion
        assert result["salary_conversion"]["monthly_k"] == 30
        assert result["salary_conversion"]["liepin_code"] == "5"

    @pytest.mark.asyncio
    async def test_direct_salary_code(self, mock_client):
        """直接传 salaryCode 时不做换算。"""
        mock_client.update_config.return_value = _ok({"updated": True})
        tool = PlatformUpdateConfigTool()
        result = await tool.execute(
            {"platform": "liepin", "config": {"salaryCode": "3"}},
            _ctx(mock_client),
        )
        assert result["success"] is True
        call_args = mock_client.update_config.call_args
        sent_config = call_args[0][1]
        assert sent_config["salaryCode"] == "3"

    @pytest.mark.asyncio
    async def test_empty_config_error(self):
        tool = PlatformUpdateConfigTool()
        result = await tool.execute(
            {"platform": "liepin", "config": {}},
            _ctx(),
        )
        assert result["success"] is False
        assert "不能为空" in result["error"]

    @pytest.mark.asyncio
    async def test_salary_conversion_low(self, mock_client):
        """monthly_salary_min=5 → 年薪6万 → salaryCode='1' (<10万)"""
        mock_client.update_config.return_value = _ok({})
        tool = PlatformUpdateConfigTool()
        result = await tool.execute(
            {"platform": "liepin", "config": {"monthly_salary_min": 5}},
            _ctx(mock_client),
        )
        call_args = mock_client.update_config.call_args
        sent_config = call_args[0][1]
        assert sent_config["salaryCode"] == "1"

    @pytest.mark.asyncio
    async def test_salary_conversion_high(self, mock_client):
        """monthly_salary_min=100 → 年薪120万 → salaryCode='7' (>100万)"""
        mock_client.update_config.return_value = _ok({})
        tool = PlatformUpdateConfigTool()
        result = await tool.execute(
            {"platform": "liepin", "config": {"monthly_salary_min": 100}},
            _ctx(mock_client),
        )
        call_args = mock_client.update_config.call_args
        sent_config = call_args[0][1]
        assert sent_config["salaryCode"] == "7"


# ---------------------------------------------------------------------------
# 5.7 — SyncJobsTool (with real DB)
# ---------------------------------------------------------------------------

class TestSyncJobsTool:
    @pytest.mark.asyncio
    async def test_sync_liepin_field_mapping_and_upsert(self, db, mock_client):
        """mock client 返回 job list → 字段映射 → DB upsert 验证"""
        mock_client.get_job_list.return_value = _ok({
            "items": [
                {
                    "jobLink": "https://liepin.com/job/123",
                    "jobTitle": "AI Engineer",
                    "compName": "TestCo",
                    "jobSalaryText": "25-50K·14薪",
                    "jobArea": "上海",
                    "jobExpReq": "3-5年",
                    "jobEduReq": "本科",
                    "compIndustry": "互联网",
                    "compScale": "500-999人",
                    "hrName": "张三",
                    "hrTitle": "HR",
                },
            ],
            "total": 1,
        })

        tool = SyncJobsTool()
        result = await tool.execute({"platform": "liepin"}, _ctx(mock_client, db))

        assert result["success"] is True
        assert result["data"]["total_fetched"] == 1
        assert result["data"]["inserted"] == 1
        assert result["data"]["updated"] == 0

        # 验证 DB 中的数据
        rows = await db.execute("SELECT * FROM jobs WHERE url = ?", ("https://liepin.com/job/123",))
        assert len(rows) == 1
        job = rows[0]
        assert job["title"] == "AI Engineer"
        assert job["company"] == "TestCo"
        assert job["salary_min"] == 25
        assert job["salary_max"] == 50
        assert job["salary_months"] == 14
        assert job["city"] == "上海"
        assert job["platform"] == "liepin"

    @pytest.mark.asyncio
    async def test_sync_upsert_updates_existing(self, db, mock_client):
        """重复 URL 应 update 而非 insert。"""
        item = {
            "jobLink": "https://liepin.com/job/dup",
            "jobTitle": "V1",
            "compName": "Co",
            "jobSalaryText": "20-30K",
            "jobArea": "北京",
        }
        mock_client.get_job_list.return_value = _ok({"items": [item], "total": 1})

        tool = SyncJobsTool()
        ctx = _ctx(mock_client, db)
        r1 = await tool.execute({"platform": "liepin"}, ctx)
        assert r1["data"]["inserted"] == 1

        # 第二次同步，title 变了
        item["jobTitle"] = "V2"
        mock_client.get_job_list.return_value = _ok({"items": [item], "total": 1})
        r2 = await tool.execute({"platform": "liepin"}, ctx)
        assert r2["data"]["updated"] == 1
        assert r2["data"]["inserted"] == 0

        rows = await db.execute("SELECT title FROM jobs WHERE url = ?", ("https://liepin.com/job/dup",))
        assert rows[0]["title"] == "V2"

    @pytest.mark.asyncio
    async def test_sync_connection_refused(self, mock_client):
        mock_client.get_job_list.return_value = _conn_refused()
        tool = SyncJobsTool()
        result = await tool.execute({"platform": "liepin"}, _ctx(mock_client))
        assert result["success"] is False
        assert "getjob 服务未启动" in result["error"]

    @pytest.mark.asyncio
    async def test_sync_invalid_platform(self):
        tool = SyncJobsTool()
        result = await tool.execute({"platform": "invalid"}, _ctx())
        assert result["success"] is False


# ---------------------------------------------------------------------------
# 5.8 — FetchJobDetailTool (with real DB)
# ---------------------------------------------------------------------------

class TestFetchJobDetailTool:
    @pytest.mark.asyncio
    async def test_fetch_updates_raw_jd(self, db, mock_client):
        """查 DB URL → mock client fetch → 更新 raw_jd"""
        # 先插入一条无 JD 的岗位
        await db.execute_write(
            "INSERT INTO jobs (url, title, platform) VALUES (?, ?, ?)",
            ("https://liepin.com/job/1", "AI岗位", "liepin"),
        )
        rows = await db.execute("SELECT id FROM jobs WHERE url = ?", ("https://liepin.com/job/1",))
        job_id = rows[0]["id"]

        mock_client.fetch_job_detail.return_value = _ok({"jd": "这是完整的岗位描述文本"})

        tool = FetchJobDetailTool()
        with patch("services.task_state.TaskStateStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store_cls.get.return_value = mock_store
            result = await tool.execute({"job_ids": [job_id]}, _ctx(mock_client, db))

        assert result["success"] is True
        assert result["fetched"] == 1

        # 验证 DB 中 raw_jd 已更新
        updated = await db.execute("SELECT raw_jd FROM jobs WHERE id = ?", (job_id,))
        assert updated[0]["raw_jd"] == "这是完整的岗位描述文本"

    @pytest.mark.asyncio
    async def test_skip_existing_jd(self, db, mock_client):
        """已有 raw_jd 且 force=False 时跳过获取。"""
        await db.execute_write(
            "INSERT INTO jobs (url, title, platform, raw_jd) VALUES (?, ?, ?, ?)",
            ("https://liepin.com/job/2", "已有JD", "liepin", "已有的JD内容"),
        )
        rows = await db.execute("SELECT id FROM jobs WHERE url = ?", ("https://liepin.com/job/2",))
        job_id = rows[0]["id"]

        tool = FetchJobDetailTool()
        with patch("services.task_state.TaskStateStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store_cls.get.return_value = mock_store
            result = await tool.execute({"job_ids": [job_id]}, _ctx(mock_client, db))

        assert result["success"] is True
        assert result["skipped"] == 1
        assert result["fetched"] == 0
        # client 不应被调用
        mock_client.fetch_job_detail.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_url_handling(self, db, mock_client):
        """URL 为空或 '#' 时报错。"""
        await db.execute_write(
            "INSERT INTO jobs (url, title, platform) VALUES (?, ?, ?)",
            ("#", "无URL岗位", "liepin"),
        )
        rows = await db.execute("SELECT id FROM jobs WHERE url = ?", ("#",))
        job_id = rows[0]["id"]

        tool = FetchJobDetailTool()
        with patch("services.task_state.TaskStateStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store_cls.get.return_value = mock_store
            result = await tool.execute({"job_ids": [job_id]}, _ctx(mock_client, db))

        assert result["failed"] == 1
        assert result["results"][0]["error"] == "无 URL"

    @pytest.mark.asyncio
    async def test_no_job_ids_error(self):
        tool = FetchJobDetailTool()
        result = await tool.execute({}, _ctx())
        assert result["success"] is False
        assert "job_id" in result["error"] or "job_ids" in result["error"]

    @pytest.mark.asyncio
    async def test_nonexistent_job_id(self, db, mock_client):
        """不存在的 job_id 应返回错误。"""
        tool = FetchJobDetailTool()
        with patch("services.task_state.TaskStateStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store_cls.get.return_value = mock_store
            result = await tool.execute({"job_ids": [99999]}, _ctx(mock_client, db))
        assert result["success"] is False
        assert "未找到" in result["error"]


# ---------------------------------------------------------------------------
# 5.9 — PlatformDeliverTool
# ---------------------------------------------------------------------------

class TestPlatformDeliverTool:
    @pytest.mark.asyncio
    async def test_delegates_to_client(self, mock_client):
        mock_client.deliver = AsyncMock(return_value=_ok({"delivered": 2}))
        tool = PlatformDeliverTool()
        result = await tool.execute(
            {"platform": "liepin", "job_ids": [1, 2]},
            _ctx(mock_client),
        )
        assert result["success"] is True
        mock_client.deliver.assert_awaited_once_with("liepin", [1, 2])

    @pytest.mark.asyncio
    async def test_empty_job_ids_error(self):
        tool = PlatformDeliverTool()
        result = await tool.execute(
            {"platform": "liepin", "job_ids": []},
            _ctx(),
        )
        assert result["success"] is False
        assert "job_ids" in result["error"]

    @pytest.mark.asyncio
    async def test_no_client_error(self):
        tool = PlatformDeliverTool()
        result = await tool.execute(
            {"platform": "liepin", "job_ids": [1]},
            {"db": AsyncMock()},  # no getjob_client
        )
        assert result["success"] is False
        assert "未配置" in result["error"]


# ---------------------------------------------------------------------------
# 5.10 — PlatformStatsTool
# ---------------------------------------------------------------------------

class TestPlatformStatsTool:
    @pytest.mark.asyncio
    async def test_filters_passed_to_client(self, mock_client):
        mock_client.get_stats.return_value = _ok({"kpi": {"total": 50}})
        tool = PlatformStatsTool()
        result = await tool.execute(
            {"platform": "liepin", "location": "上海", "minK": 20, "keyword": "AI"},
            _ctx(mock_client),
        )
        assert result["success"] is True
        # 验证 filters 被正确传递
        mock_client.get_stats.assert_awaited_once()
        call_kwargs = mock_client.get_stats.call_args
        # get_stats(platform, **filters)
        assert call_kwargs[0][0] == "liepin"
        assert call_kwargs[1]["location"] == "上海"
        assert call_kwargs[1]["minK"] == 20
        assert call_kwargs[1]["keyword"] == "AI"

    @pytest.mark.asyncio
    async def test_connection_refused(self, mock_client):
        mock_client.get_stats.return_value = _conn_refused()
        tool = PlatformStatsTool()
        result = await tool.execute({"platform": "liepin"}, _ctx(mock_client))
        assert result["success"] is False
        assert "getjob 服务未启动" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_platform(self):
        tool = PlatformStatsTool()
        result = await tool.execute({"platform": "nope"}, _ctx())
        assert result["success"] is False


# ---------------------------------------------------------------------------
# 5.11 — GetjobServiceManagerTool
# ---------------------------------------------------------------------------

class TestGetjobServiceManagerTool:
    @pytest.mark.asyncio
    async def test_check_calls_health_check(self, mock_client):
        mock_client.health_check.return_value = _ok({"status": "ok"})
        tool = GetjobServiceManagerTool()
        result = await tool.execute({"action": "check"}, _ctx(mock_client))
        assert result["success"] is True
        assert result["running"] is True
        mock_client.health_check.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_not_running(self, mock_client):
        mock_client.health_check.return_value = _err("connection refused")
        tool = GetjobServiceManagerTool()
        result = await tool.execute({"action": "check"}, _ctx(mock_client))
        assert result["success"] is True
        assert result["running"] is False

    @pytest.mark.asyncio
    async def test_stop_no_process(self):
        """没有由 agent 启动的进程时 stop 应成功。"""
        # 确保类级别 _process 为 None
        GetjobServiceManagerTool._process = None
        tool = GetjobServiceManagerTool()
        result = await tool.execute({"action": "stop"}, _ctx())
        assert result["success"] is True
        assert "没有" in result["message"]

    @pytest.mark.asyncio
    async def test_start_already_running(self, mock_client):
        """服务已在运行时 start 应直接返回成功。"""
        mock_client.health_check.return_value = _ok({"status": "ok"})
        tool = GetjobServiceManagerTool()
        result = await tool.execute({"action": "start"}, _ctx(mock_client))
        assert result["success"] is True
        assert "已经在运行" in result["message"]

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        tool = GetjobServiceManagerTool()
        result = await tool.execute({"action": "restart"}, _ctx())
        assert result["success"] is False
        assert "未知" in result["error"]
