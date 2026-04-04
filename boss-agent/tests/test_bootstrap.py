"""
Bootstrap 模块单元测试

验证 Tool 注册和 get_all_schemas() 输出符合 LLM Function Calling 格式。
"""

from __future__ import annotations

import pytest

from agent.bootstrap import create_tool_registry, bootstrap
from agent.tool_registry import ToolRegistry


# Expected tool names from Phase 3 Data Tools
EXPECTED_TOOLS = {
    "save_job",
    "save_application",
    "update_interview_status",
    "get_interview_funnel",
    "get_stats",
    "add_to_blacklist",
    "remove_from_blacklist",
    "export_csv",
}


class TestCreateToolRegistry:
    def test_returns_registry(self):
        reg = create_tool_registry()
        assert isinstance(reg, ToolRegistry)

    def test_all_data_tools_registered(self):
        reg = create_tool_registry()
        registered = set(reg.list_tool_names())
        assert EXPECTED_TOOLS.issubset(registered), (
            f"Missing tools: {EXPECTED_TOOLS - registered}"
        )

    def test_tool_count(self):
        reg = create_tool_registry()
        assert reg.tool_count >= len(EXPECTED_TOOLS)

    def test_no_duplicate_names(self):
        reg = create_tool_registry()
        names = reg.list_tool_names()
        assert len(names) == len(set(names)), "Duplicate tool names detected"


class TestSchemaCompliance:
    """Verify get_all_schemas() output conforms to LLM Function Calling format."""

    def test_all_schemas_have_correct_structure(self):
        reg = create_tool_registry()
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
        reg = create_tool_registry()
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
