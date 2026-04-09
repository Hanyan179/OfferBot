"""
单元测试：get_data_status 元工具

覆盖：
- 正常返回结构完整性（mock DB）  → Requirements 3.1
- 数据库异常处理               → Requirements 3.3
- 数据库不可用                 → Requirements 3.3
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tools.meta.get_data_status import GetDataStatusTool


def _run(coro):
    """Run an async coroutine synchronously (matches PBT test pattern)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tool():
    return GetDataStatusTool()


def _make_db_mock(
    has_profile_cnt: int = 1,
    job_count: int = 10,
    jd_count: int = 5,
    application_count: int = 3,
) -> AsyncMock:
    """Create a mock DB that returns predetermined counts."""
    db = AsyncMock()

    async def fake_execute(sql: str, *args, **kwargs):
        if "resumes" in sql:
            return [{"cnt": has_profile_cnt}]
        if "jd IS NOT NULL" in sql:
            return [{"cnt": jd_count}]
        if "jobs" in sql:
            return [{"cnt": job_count}]
        if "applications" in sql:
            return [{"cnt": application_count}]
        return [{"cnt": 0}]

    db.execute = AsyncMock(side_effect=fake_execute)
    return db


# ---------------------------------------------------------------------------
# Tests: 正常返回结构完整性 (Requirement 3.1)
# ---------------------------------------------------------------------------

class TestGetDataStatusNormal:
    """Requirement 3.1: 返回结构包含所有必需字段。"""

    def test_returns_all_required_fields(self, tool):
        ctx: dict[str, Any] = {"db": _make_db_mock()}
        result = _run(tool.execute({}, ctx))

        assert result["success"] is True
        for field in ("has_profile", "job_count", "jd_count", "application_count", "memory_category_count"):
            assert field in result, f"Missing field: {field}"

    def test_has_profile_true_when_count_positive(self, tool):
        ctx: dict[str, Any] = {"db": _make_db_mock(has_profile_cnt=1)}
        result = _run(tool.execute({}, ctx))
        assert result["has_profile"] is True

    def test_has_profile_false_when_count_zero(self, tool):
        ctx: dict[str, Any] = {"db": _make_db_mock(has_profile_cnt=0)}
        result = _run(tool.execute({}, ctx))
        assert result["has_profile"] is False

    def test_counts_match_db_values(self, tool):
        ctx: dict[str, Any] = {"db": _make_db_mock(
            job_count=42, jd_count=17, application_count=8
        )}
        result = _run(tool.execute({}, ctx))
        assert result["job_count"] == 42
        assert result["jd_count"] == 17
        assert result["application_count"] == 8

    def test_memory_category_count_is_int(self, tool):
        ctx: dict[str, Any] = {"db": _make_db_mock()}
        result = _run(tool.execute({}, ctx))
        assert isinstance(result["memory_category_count"], int)


# ---------------------------------------------------------------------------
# Tests: 数据库异常处理 (Requirement 3.3)
# ---------------------------------------------------------------------------

class TestGetDataStatusErrorHandling:
    """Requirement 3.3: 数据库异常返回错误信息而非抛出异常。"""

    def test_db_exception_returns_error(self, tool):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("connection lost"))
        ctx: dict[str, Any] = {"db": db}

        result = _run(tool.execute({}, ctx))

        assert result["success"] is False
        assert "error" in result
        assert "connection lost" in result["error"]

    def test_db_none_returns_error(self, tool):
        ctx: dict[str, Any] = {"db": None}
        result = _run(tool.execute({}, ctx))
        assert result["success"] is False
        assert "数据库不可用" in result["error"]

    def test_db_missing_from_context_returns_error(self, tool):
        result = _run(tool.execute({}, {}))
        assert result["success"] is False

    def test_db_exception_does_not_raise(self, tool):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("timeout"))
        ctx: dict[str, Any] = {"db": db}

        # Should NOT raise — must return dict
        result = _run(tool.execute({}, ctx))
        assert isinstance(result, dict)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Tests: bootstrap 后各工具的 toolset 归属正确 (Requirements 7.1-7.8)
# ---------------------------------------------------------------------------

from agent.bootstrap import create_tool_registry


@pytest.fixture(scope="module")
def registry():
    reg, _ = create_tool_registry()
    return reg


def _tool_names(registry, toolset: str) -> set[str]:
    return {t.name for t in registry.get_tools_by_toolset(toolset)}


class TestBootstrapToolsetAssignment:
    """Requirements 7.1-7.8: bootstrap 后各工具的 toolset 归属正确。"""

    # Req 7.1: core 工具集包含 10 个工具
    def test_core_toolset_count(self, registry):
        assert len(_tool_names(registry, "core")) == 10

    def test_core_toolset_names(self, registry):
        expected = {
            "get_user_profile", "query_jobs", "rag_query", "get_stats",
            "job_count", "get_memory", "search_memory",
            "get_user_cognitive_model", "activate_toolset", "get_data_status",
        }
        assert _tool_names(registry, "core") == expected

    # Req 7.2: crawl 工具集
    def test_crawl_toolset(self, registry):
        expected = {
            "fetch_job_detail", "platform_start_task", "platform_stop_task",
            "sync_jobs", "platform_status",
        }
        assert _tool_names(registry, "crawl") == expected

    # Req 7.3: deliver 工具集
    def test_deliver_toolset(self, registry):
        expected = {"platform_deliver", "save_application"}
        assert _tool_names(registry, "deliver") == expected

    # Req 7.4: admin 工具集
    def test_admin_toolset(self, registry):
        expected = {
            "platform_get_config", "platform_update_config",
            "getjob_service_manage", "platform_stats", "delete_jobs",
        }
        assert _tool_names(registry, "admin") == expected

    # Req 7.5: web 工具集
    def test_web_toolset(self, registry):
        expected = {"web_fetch", "web_search"}
        assert _tool_names(registry, "web") == expected

    # Req 7.6: sub_agent 工具集
    def test_sub_agent_toolset(self, registry):
        expected = {
            "save_memory", "update_memory", "delete_memory",
            "list_memory_categories",
        }
        assert _tool_names(registry, "sub_agent") == expected

    # Req 7.7: deprecated 工具集
    def test_deprecated_toolset(self, registry):
        expected = {
            "save_job", "add_to_blacklist", "remove_from_blacklist",
            "export_csv", "update_user_profile",
            "get_skill_content",
        }
        assert _tool_names(registry, "deprecated") == expected

    # sub_agent 和 deprecated 隔离：不出现在 core/crawl/deliver/admin/web 中
    def test_sub_agent_isolated_from_scene_toolsets(self, registry):
        sub_agent_names = _tool_names(registry, "sub_agent")
        for ts in ("core", "crawl", "deliver", "admin", "web"):
            assert sub_agent_names.isdisjoint(_tool_names(registry, ts)), \
                f"sub_agent tools leaked into {ts}"

    def test_deprecated_isolated_from_scene_toolsets(self, registry):
        deprecated_names = _tool_names(registry, "deprecated")
        for ts in ("core", "crawl", "deliver", "admin", "web"):
            assert deprecated_names.isdisjoint(_tool_names(registry, ts)), \
                f"deprecated tools leaked into {ts}"

    # Req 7.8: 只读记忆工具在 core 中
    def test_readonly_memory_in_core(self, registry):
        core = _tool_names(registry, "core")
        assert "get_memory" in core
        assert "search_memory" in core
        assert "get_user_cognitive_model" in core

    # Req 7.9: 现有 Tool 的 execute() 实现保持不变 — 验证所有工具都有 execute 方法
    def test_all_tools_have_execute(self, registry):
        for schema in registry.get_all_schemas():
            tool = registry.get_tool(schema["function"]["name"])
            assert tool is not None
            assert hasattr(tool, "execute")


# ---------------------------------------------------------------------------
# Tests: System Prompt 内容验证 (Requirements 5.1-5.6)
# ---------------------------------------------------------------------------

import inspect
from agent.system_prompt import (
    SYSTEM_PROMPT,
    TOOLSET_ROUTING_GUIDE,
    MEMORY_PROMPT_SECTION,
    build_full_system_prompt,
)


class TestSystemPromptContent:
    """Requirements 5.1-5.6: System Prompt 精简与路由指引。"""

    def test_contains_toolset_routing_keywords(self):
        """Req 5.2: prompt 包含工具集路由关键词（场景名称，不硬编码工具名）。"""
        prompt = build_full_system_prompt()
        for keyword in ("crawl", "deliver", "admin", "web", "工具集路由"):
            assert keyword in prompt, f"Missing routing keyword: {keyword}"

    def test_contains_core_persona(self):
        """Req 5.1: 保留核心人设描述。"""
        prompt = build_full_system_prompt()
        assert "MooBot" in prompt
        assert "求职" in prompt

    def test_no_rag_search_strategy_block(self):
        """Req 5.3: 不含独立的 RAG_SEARCH_STRATEGY 策略块（已被 TOOLSET_ROUTING_GUIDE 替代）。"""
        # RAG_SEARCH_STRATEGY 应该只是 TOOLSET_ROUTING_GUIDE 的别名，
        # 最终 prompt 中不应出现旧的详细搜索策略段落标题
        from agent.system_prompt import RAG_SEARCH_STRATEGY
        assert RAG_SEARCH_STRATEGY is TOOLSET_ROUTING_GUIDE

    def test_contains_memory_section(self):
        """Req 5.4: 保留记忆系统指引。"""
        prompt = build_full_system_prompt()
        assert "记忆系统" in prompt
        assert "记忆分类" in prompt

    def test_contains_skills_section_when_provided(self):
        """Req 5.5: 保留 Skills 集成段落。"""
        skills_text = "## 可用 Skills\n- 简历生成"
        prompt = build_full_system_prompt(skills_prompt_section=skills_text)
        assert "可用 Skills" in prompt
        assert "简历生成" in prompt

    def test_build_full_system_prompt_signature_compatible(self):
        """Req 5.6: build_full_system_prompt() 签名向后兼容。"""
        sig = inspect.signature(build_full_system_prompt)
        # 可以无参调用
        assert build_full_system_prompt() is not None
        # 接受 skills_prompt_section 参数
        params = sig.parameters
        assert "skills_prompt_section" in params
        assert params["skills_prompt_section"].default == ""

    def test_no_args_required(self):
        """Req 5.6: 无参调用不报错，返回非空字符串。"""
        result = build_full_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 100
