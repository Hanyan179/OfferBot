"""
Bootstrap 模块单元测试

验证 Tool 注册和 get_all_schemas() 输出符合 LLM Function Calling 格式。
"""

from __future__ import annotations

from agent.bootstrap import bootstrap, create_tool_registry
from agent.tool_registry import ToolRegistry

# Expected tool names from Phase 3 Data Tools + Web Tools + Getjob Tools + AI Tools
EXPECTED_TOOLS = {
    "save_job",
    "save_application",
    "get_stats",
    "add_to_blacklist",
    "remove_from_blacklist",
    "export_csv",
    "web_fetch",
    "web_search",
    "platform_status",
    "platform_start_task",
    "platform_stop_task",
    "platform_get_config",
    "platform_update_config",
    "sync_jobs",
    "platform_stats",
    "get_skill_content",
}


class TestCreateToolRegistry:
    def test_returns_registry(self):
        reg, _sl = create_tool_registry()
        assert isinstance(reg, ToolRegistry)

    def test_all_data_tools_registered(self):
        reg, _sl = create_tool_registry()
        registered = set(reg.list_tool_names())
        assert EXPECTED_TOOLS.issubset(registered), (
            f"Missing tools: {EXPECTED_TOOLS - registered}"
        )

    def test_tool_count(self):
        reg, _sl = create_tool_registry()
        assert reg.tool_count >= len(EXPECTED_TOOLS)

    def test_no_duplicate_names(self):
        reg, _sl = create_tool_registry()
        names = reg.list_tool_names()
        assert len(names) == len(set(names)), "Duplicate tool names detected"


class TestSchemaCompliance:
    """Verify get_all_schemas() output conforms to LLM Function Calling format."""

    def test_all_schemas_have_correct_structure(self):
        reg, _sl = create_tool_registry()
        schemas = reg.get_all_schemas()

        assert len(schemas) >= len(EXPECTED_TOOLS)

        for schema in schemas:
            # Top-level: {"type": "function", "function": {...}}
            assert schema["type"] == "function"
            assert "function" in schema

            func = schema["function"]

            # name: non-empty string
            assert isinstance(func["name"], str)
            assert len(func["name"]) > 0

            # description: non-empty string
            assert isinstance(func["description"], str)
            assert len(func["description"]) > 0

            # parameters: valid JSON Schema object
            params = func["parameters"]
            assert isinstance(params, dict)
            assert params.get("type") == "object"
            assert "properties" in params

    def test_each_tool_has_schema(self):
        reg, _sl = create_tool_registry()
        schemas = reg.get_all_schemas()
        schema_names = {s["function"]["name"] for s in schemas}

        for tool_name in EXPECTED_TOOLS:
            assert tool_name in schema_names, f"Missing schema for tool: {tool_name}"


class TestBootstrap:
    def test_returns_all_components(self):
        from unittest.mock import MagicMock
        mock_db = MagicMock()

        result = bootstrap(mock_db, api_key="test-key", model="qwen-plus")

        assert "registry" in result
        assert "planner" in result
        assert "executor" in result
        assert "getjob_client" in result
        assert "skill_loader" in result
        assert isinstance(result["registry"], ToolRegistry)

    def test_planner_has_registry(self):
        from unittest.mock import MagicMock
        mock_db = MagicMock()

        result = bootstrap(mock_db, api_key="test-key")

        assert result["planner"].tool_registry is result["registry"]

    def test_executor_has_registry(self):
        from unittest.mock import MagicMock
        mock_db = MagicMock()

        result = bootstrap(mock_db, api_key="test-key")

        assert result["executor"].tool_registry is result["registry"]


class TestGetSkillContentRegistration:
    """验证 get_skill_content Tool 注册到 ToolRegistry。需求: 7.2"""

    def test_get_skill_content_registered(self):
        reg, _sl = create_tool_registry()
        assert reg.has_tool("get_skill_content"), "get_skill_content should be registered"

    def test_get_skill_content_category_is_ai(self):
        reg, _sl = create_tool_registry()
        tool = reg.get_tool("get_skill_content")
        assert tool is not None
        assert tool.category == "ai"

    def test_skill_loader_returned(self):
        _reg, sl = create_tool_registry()
        assert sl is not None
        from agent.skill_loader import SkillLoader
        assert isinstance(sl, SkillLoader)


class TestWebToolsRegistration:
    """验证 Web Tools（web_fetch / web_search）注册到 ToolRegistry。需求: 3.5"""

    def test_web_fetch_registered(self):
        reg, _sl = create_tool_registry()
        assert reg.has_tool("web_fetch"), "web_fetch should be registered"

    def test_web_search_registered(self):
        reg, _sl = create_tool_registry()
        assert reg.has_tool("web_search"), "web_search should be registered"

    def test_web_fetch_category_is_browser(self):
        reg, _sl = create_tool_registry()
        tool = reg.get_tool("web_fetch")
        assert tool is not None
        assert tool.category == "browser"

    def test_web_search_category_is_browser(self):
        reg, _sl = create_tool_registry()
        tool = reg.get_tool("web_search")
        assert tool is not None
        assert tool.category == "browser"

    def test_get_tools_by_browser_category(self):
        reg, _sl = create_tool_registry()
        browser_tools = reg.get_tools_by_category("browser")
        browser_names = {t.name for t in browser_tools}
        assert {"web_fetch", "web_search"}.issubset(browser_names), (
            f"Expected web_fetch and web_search in browser category, got {browser_names}"
        )
