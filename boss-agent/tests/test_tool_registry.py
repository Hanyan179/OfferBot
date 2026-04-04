"""tool_registry 模块单元测试 + 属性测试"""

from typing import Any

import pytest
from hypothesis import given, settings, strategies as st

from agent.tool_registry import Tool, ToolRegistry


# ---------------------------------------------------------------------------
# Concrete Tool helpers for testing
# ---------------------------------------------------------------------------

class DummyTool(Tool):
    """测试用的具体 Tool 实现"""

    def __init__(
        self,
        name: str = "dummy",
        description: str | None = None,
        category: str = "general",
        concurrency_safe: bool = False,
        parameters_schema: dict | None = None,
    ):
        self._name = name
        self._description = description or f"A dummy tool named {name}"
        self._category = category
        self._concurrency_safe = concurrency_safe
        self._parameters_schema = parameters_schema or {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "test input"},
            },
            "required": ["input"],
        }

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters_schema(self) -> dict:
        return self._parameters_schema

    @property
    def is_concurrency_safe(self) -> bool:
        return self._concurrency_safe

    @property
    def category(self) -> str:
        return self._category

    async def execute(self, params: dict, context: Any) -> Any:
        return {"echo": params.get("input")}


# ---------------------------------------------------------------------------
# Tool ABC tests
# ---------------------------------------------------------------------------

class TestToolABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Tool()  # type: ignore[abstract]

    def test_concrete_tool_properties(self):
        t = DummyTool(name="search_jobs")
        assert t.name == "search_jobs"
        assert "search_jobs" in t.description
        assert isinstance(t.parameters_schema, dict)

    def test_default_concurrency_safe_is_false(self):
        t = DummyTool()
        assert t.is_concurrency_safe is False

    def test_concurrency_safe_override(self):
        t = DummyTool(concurrency_safe=True)
        assert t.is_concurrency_safe is True

    def test_default_category(self):
        t = DummyTool()
        assert t.category == "general"

    def test_custom_category(self):
        t = DummyTool(category="browser")
        assert t.category == "browser"

    def test_custom_parameters_schema(self):
        schema = {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        }
        t = DummyTool(parameters_schema=schema)
        assert t.parameters_schema == schema


# ---------------------------------------------------------------------------
# ToolRegistry unit tests
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = DummyTool(name="my_tool")
        reg.register(tool)
        assert reg.get_tool("my_tool") is tool

    def test_get_nonexistent_returns_none(self):
        reg = ToolRegistry()
        assert reg.get_tool("nonexistent") is None

    def test_register_overwrites_by_default(self):
        reg = ToolRegistry()
        t1 = DummyTool(name="tool")
        t2 = DummyTool(name="tool")
        reg.register(t1)
        reg.register(t2)
        assert reg.get_tool("tool") is t2

    def test_register_no_overwrite_raises(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="tool"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(DummyTool(name="tool"), allow_overwrite=False)

    def test_get_all_schemas_empty(self):
        reg = ToolRegistry()
        assert reg.get_all_schemas() == []

    def test_get_all_schemas_format(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="search_jobs"))
        reg.register(DummyTool(name="parse_jd"))
        schemas = reg.get_all_schemas()
        assert len(schemas) == 2
        for schema in schemas:
            assert schema["type"] == "function"
            func = schema["function"]
            assert isinstance(func["name"], str) and len(func["name"]) > 0
            assert isinstance(func["description"], str) and len(func["description"]) > 0
            assert isinstance(func["parameters"], dict)

    def test_get_tools_by_category(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="t1", category="browser"))
        reg.register(DummyTool(name="t2", category="ai"))
        reg.register(DummyTool(name="t3", category="browser"))
        browser_tools = reg.get_tools_by_category("browser")
        assert len(browser_tools) == 2
        assert {t.name for t in browser_tools} == {"t1", "t3"}

    def test_get_tools_by_category_empty(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="t1", category="ai"))
        assert reg.get_tools_by_category("browser") == []

    def test_list_tool_names(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="a"))
        reg.register(DummyTool(name="b"))
        assert sorted(reg.list_tool_names()) == ["a", "b"]

    def test_list_tool_names_empty(self):
        reg = ToolRegistry()
        assert reg.list_tool_names() == []

    def test_tool_count(self):
        reg = ToolRegistry()
        assert reg.tool_count == 0
        reg.register(DummyTool(name="x"))
        assert reg.tool_count == 1
        reg.register(DummyTool(name="y"))
        assert reg.tool_count == 2

    def test_has_tool(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="exists"))
        assert reg.has_tool("exists") is True
        assert reg.has_tool("nope") is False

    def test_unregister(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="rm_me"))
        assert reg.unregister("rm_me") is True
        assert reg.get_tool("rm_me") is None
        assert reg.tool_count == 0

    def test_unregister_nonexistent(self):
        reg = ToolRegistry()
        assert reg.unregister("ghost") is False

    def test_register_multiple_tools(self):
        reg = ToolRegistry()
        names = [f"tool_{i}" for i in range(10)]
        for n in names:
            reg.register(DummyTool(name=n))
        assert reg.tool_count == 10
        assert sorted(reg.list_tool_names()) == sorted(names)
        schemas = reg.get_all_schemas()
        assert len(schemas) == 10


# ---------------------------------------------------------------------------
# Hypothesis strategies for property-based testing
# ---------------------------------------------------------------------------

# Strategy: generate valid tool names (non-empty, identifier-like strings)
st_tool_name = st.from_regex(r"[a-z][a-z0-9_]{0,29}", fullmatch=True)

# Strategy: generate non-empty descriptions
st_description = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())

# Strategy: generate valid JSON Schema property types
st_json_type = st.sampled_from(["string", "integer", "number", "boolean", "array", "object"])

# Strategy: generate a single JSON Schema property
st_schema_property = st.fixed_dictionaries({
    "type": st_json_type,
    "description": st.text(min_size=1, max_size=50).filter(lambda s: s.strip()),
})

# Strategy: generate a valid parameters_schema (JSON Schema object)
@st.composite
def st_parameters_schema(draw):
    num_props = draw(st.integers(min_value=0, max_value=5))
    prop_names = draw(
        st.lists(
            st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True),
            min_size=num_props,
            max_size=num_props,
            unique=True,
        )
    )
    properties = {}
    for pname in prop_names:
        properties[pname] = draw(st_schema_property)
    # required is a subset of property names
    required = draw(
        st.lists(st.sampled_from(prop_names) if prop_names else st.nothing(), max_size=len(prop_names), unique=True)
    ) if prop_names else []
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


# Strategy: generate a complete tool configuration
@st.composite
def st_tool_config(draw):
    return {
        "name": draw(st_tool_name),
        "description": draw(st_description),
        "parameters_schema": draw(st_parameters_schema()),
        "category": draw(st.sampled_from(["general", "browser", "ai", "data"])),
        "concurrency_safe": draw(st.booleans()),
    }


# ---------------------------------------------------------------------------
# Property-based tests — Property 2: Tool Registry Schema 合规性
# ---------------------------------------------------------------------------

class TestToolRegistrySchemaCompliance:
    """
    # Feature: boss-agent-core, Property 2: Tool Registry Schema 合规性
    #
    # For any registered Tool, the JSON Schema returned by ToolRegistry
    # should contain name (non-empty string), description (non-empty string),
    # parameters (valid JSON Schema object), and conform to LLM Function
    # Calling protocol format.
    """

    @given(config=st_tool_config())
    @settings(max_examples=100)
    def test_single_tool_schema_compliance(self, config: dict):
        """
        # Feature: boss-agent-core, Property 2: Tool Registry Schema 合规性
        For any single registered tool, the schema must be LLM Function Calling compliant.
        """
        tool = DummyTool(
            name=config["name"],
            description=config["description"],
            parameters_schema=config["parameters_schema"],
            category=config["category"],
            concurrency_safe=config["concurrency_safe"],
        )
        reg = ToolRegistry()
        reg.register(tool)
        schemas = reg.get_all_schemas()

        assert len(schemas) == 1
        schema = schemas[0]

        # Top-level must have "type": "function"
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
        assert isinstance(params["properties"], dict)

    @given(configs=st.lists(st_tool_config(), min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_multiple_tools_schema_compliance(self, configs: list[dict]):
        """
        # Feature: boss-agent-core, Property 2: Tool Registry Schema 合规性
        For any set of registered tools, all schemas must be compliant.
        **Validates: Requirements 1.3**
        """
        reg = ToolRegistry()
        # Deduplicate by name (last one wins, matching register behavior)
        unique_configs: dict[str, dict] = {}
        for cfg in configs:
            unique_configs[cfg["name"]] = cfg

        for cfg in unique_configs.values():
            reg.register(DummyTool(
                name=cfg["name"],
                description=cfg["description"],
                parameters_schema=cfg["parameters_schema"],
                category=cfg["category"],
                concurrency_safe=cfg["concurrency_safe"],
            ))

        schemas = reg.get_all_schemas()
        assert len(schemas) == len(unique_configs)

        schema_names = set()
        for schema in schemas:
            # Structure check
            assert schema["type"] == "function"
            func = schema["function"]
            assert isinstance(func["name"], str) and len(func["name"]) > 0
            assert isinstance(func["description"], str) and len(func["description"]) > 0
            assert isinstance(func["parameters"], dict)
            assert func["parameters"].get("type") == "object"
            schema_names.add(func["name"])

        # All registered tool names appear in schemas
        assert schema_names == set(unique_configs.keys())
