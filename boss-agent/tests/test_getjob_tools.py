"""
getjob Tool 层单元测试
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from tools.getjob.platform_status import PlatformStatusTool
from tools.getjob.platform_control import PlatformStartTaskTool, PlatformStopTaskTool
from tools.getjob.platform_config import PlatformGetConfigTool, PlatformUpdateConfigTool
from tools.getjob.platform_sync import SyncJobsTool, parse_salary, format_salary
from tools.getjob.platform_stats import PlatformStatsTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(client_mock=None, db_mock=None):
    return {
        "getjob_client": client_mock or AsyncMock(),
        "db": db_mock or AsyncMock(),
    }


def _ok_result(data=None):
    return {"success": True, "data": data or {}, "error": None}


def _err_result(error="some error"):
    return {"success": False, "data": None, "error": error}


def _conn_refused_result():
    return {"success": False, "data": None, "error": "无法连接 getjob 服务 (http://localhost:8888)"}


# ---------------------------------------------------------------------------
# parse_salary tests
# ---------------------------------------------------------------------------

class TestParseSalary:
    def test_range(self):
        assert parse_salary("25-50K") == (25, 50)

    def test_range_with_k(self):
        assert parse_salary("25K-50K") == (25, 50)

    def test_range_with_months(self):
        assert parse_salary("25-50K·14薪") == (25, 50)

    def test_negotiable(self):
        assert parse_salary("面议") == (None, None)

    def test_none(self):
        assert parse_salary(None) == (None, None)

    def test_empty(self):
        assert parse_salary("") == (None, None)

    def test_single_k(self):
        assert parse_salary("30K") == (30, 30)

    def test_round_trip(self):
        """format → parse round-trip."""
        s = format_salary(25, 50)
        assert parse_salary(s) == (25, 50)


# ---------------------------------------------------------------------------
# PlatformStatusTool
# ---------------------------------------------------------------------------

class TestPlatformStatusTool:
    @pytest.mark.asyncio
    async def test_ok(self):
        client = AsyncMock()
        client.get_status.return_value = _ok_result({"isRunning": False, "isLoggedIn": True})
        tool = PlatformStatusTool()
        result = await tool.execute({"platform": "liepin"}, _make_context(client))
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_invalid_platform(self):
        tool = PlatformStatusTool()
        result = await tool.execute({"platform": "boss"}, _make_context())
        assert result["success"] is False
        assert "不支持" in result["error"]

    @pytest.mark.asyncio
    async def test_service_down(self):
        client = AsyncMock()
        client.get_status.return_value = _conn_refused_result()
        tool = PlatformStatusTool()
        result = await tool.execute({"platform": "liepin"}, _make_context(client))
        assert result["success"] is False
        assert "getjob 服务未启动" in result["error"]


# ---------------------------------------------------------------------------
# PlatformStartTaskTool / PlatformStopTaskTool
# ---------------------------------------------------------------------------

class TestPlatformControlTools:
    @pytest.mark.asyncio
    async def test_start_ok(self):
        client = AsyncMock()
        client.start_task.return_value = _ok_result({"status": "started"})
        tool = PlatformStartTaskTool()
        result = await tool.execute({"platform": "zhilian"}, _make_context(client))
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_stop_no_running(self):
        client = AsyncMock()
        client.stop_task.return_value = _err_result("没有正在运行的任务")
        tool = PlatformStopTaskTool()
        result = await tool.execute({"platform": "liepin"}, _make_context(client))
        assert result["success"] is True
        assert "没有运行中" in result.get("message", "")


# ---------------------------------------------------------------------------
# PlatformGetConfigTool / PlatformUpdateConfigTool
# ---------------------------------------------------------------------------

class TestPlatformConfigTools:
    @pytest.mark.asyncio
    async def test_get_config(self):
        client = AsyncMock()
        client.get_config.return_value = _ok_result({"config": {"keywords": "AI"}})
        tool = PlatformGetConfigTool()
        result = await tool.execute({"platform": "liepin"}, _make_context(client))
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_config(self):
        client = AsyncMock()
        client.update_config.return_value = _ok_result({"id": 1, "scrapeOnly": True})
        tool = PlatformUpdateConfigTool()
        result = await tool.execute(
            {"platform": "liepin", "config": {"scrapeOnly": True}},
            _make_context(client),
        )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# PlatformStatsTool
# ---------------------------------------------------------------------------

class TestPlatformStatsTool:
    @pytest.mark.asyncio
    async def test_stats_ok(self):
        client = AsyncMock()
        client.get_stats.return_value = _ok_result({"kpi": {"total": 100}})
        tool = PlatformStatsTool()
        result = await tool.execute({"platform": "liepin"}, _make_context(client))
        assert result["success"] is True


# ---------------------------------------------------------------------------
# SyncJobsTool
# ---------------------------------------------------------------------------

class TestSyncJobsTool:
    @pytest.mark.asyncio
    async def test_sync_liepin(self):
        client = AsyncMock()
        client.get_job_list.return_value = _ok_result({
            "items": [
                {
                    "jobLink": "https://liepin.com/job/123",
                    "jobTitle": "AI Engineer",
                    "compName": "TestCo",
                    "jobSalaryText": "25-50K",
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
        db = AsyncMock()
        db.execute.return_value = []  # no existing record

        tool = SyncJobsTool()
        result = await tool.execute(
            {"platform": "liepin"},
            _make_context(client, db),
        )
        assert result["success"] is True
        assert result["data"]["inserted"] == 1
        assert result["data"]["total_fetched"] == 1
