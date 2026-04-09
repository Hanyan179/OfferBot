"""
Doc Generator 单元测试 + 属性测试

覆盖:
- introspect_tool 单元测试
- Property 1: Doc Generation Round-Trip
- Property 2: Doc Section Completeness
- Property 3: Catalog Category Grouping
"""

from __future__ import annotations

import re
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from agent.tool_registry import Tool, ToolRegistry
from scripts.generate_tool_docs import (
    format_tool_section,
    generate_catalog,
    introspect_tool,
)

# ---------------------------------------------------------------------------
# DummyTool helper (mirrors test_tool_registry.py pattern)
# ---------------------------------------------------------------------------


class DummyTool(Tool):
    """测试用的具体 Tool 实现，支持所有可配置属性。"""

    def __init__(
        self,
        name: str = "dummy",
        description: str | None = None,
        category: str = "general",
        toolset: str = "core",
        concurrency_safe: bool = False,
        display_name: str | None = None,
        parameters_schema: dict | None = None,
    ):
        self._name = name
        self._description = description or f"A dummy tool named {name}"
        self._category = category
        self._toolset = toolset
        self._concurrency_safe = concurrency_safe
        self._display_name = display_name or name
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
    def display_name(self) -> str:
        return self._display_name

    @property
    def parameters_schema(self) -> dict:
        return self._parameters_schema

    @property
    def is_concurrency_safe(self) -> bool:
        return self._concurrency_safe

    @property
    def category(self) -> str:
        return self._category

    @property
    def toolset(self) -> str:
        return self._toolset

    async def execute(self, params: dict, context: Any) -> Any:
        return {"echo": params}


# ---------------------------------------------------------------------------
# Markdown parser for round-trip testing
# ---------------------------------------------------------------------------


def parse_tool_section(markdown: str) -> dict:
    """Parse a Markdown tool section back into a structured dict.

    This is the inverse of format_tool_section, used for round-trip testing.
    """
    info: dict[str, Any] = {}

    # Parse header: ### `{name}` — {display_name}
    header_match = re.search(r"^### `([^`]+)` — (.+)$", markdown, re.MULTILINE)
    assert header_match, f"Could not parse header from:\n{markdown}"
    info["name"] = header_match.group(1)
    info["display_name"] = header_match.group(2).strip()

    # Parse description: > {description}
    desc_match = re.search(r"^> (.+)$", markdown, re.MULTILINE)
    assert desc_match, f"Could not parse description from:\n{markdown}"
    info["description"] = desc_match.group(1).strip()

    # Parse category: - **分类**: {category}
    cat_match = re.search(r"- \*\*分类\*\*: (.+)$", markdown, re.MULTILINE)
    assert cat_match
    info["category"] = cat_match.group(1).strip()

    # Parse toolset: - **工具集**: {toolset}
    ts_match = re.search(r"- \*\*工具集\*\*: (.+)$", markdown, re.MULTILINE)
    assert ts_match
    info["toolset"] = ts_match.group(1).strip()

    # Parse concurrency: - **并发安全**: ✅ 是 / ❌ 否
    conc_match = re.search(r"- \*\*并发安全\*\*: (.+)$", markdown, re.MULTILINE)
    assert conc_match
    info["concurrency_safe"] = "✅" in conc_match.group(1)

    # Parse parameters from table
    info["parameters"] = []
    # Match table rows: | `param_name` | `type` | required | desc |
    param_pattern = re.compile(
        r"^\| `([^`]+)` \| `([^`]+)` \| (✅|) \| (.*?) \|$", re.MULTILINE
    )
    for m in param_pattern.finditer(markdown):
        param: dict[str, Any] = {
            "name": m.group(1),
            "type": m.group(2),
            "required": m.group(3) == "✅",
            "description": m.group(4).strip(),
        }
        info["parameters"].append(param)

    return info


# ---------------------------------------------------------------------------
# 3.1  introspect_tool 单元测试
# ---------------------------------------------------------------------------


class TestIntrospectTool:
    """introspect_tool 单元测试"""

    def test_basic_introspection(self):
        tool = DummyTool(
            name="search_jobs",
            description="搜索岗位",
            category="data",
            toolset="core",
            concurrency_safe=True,
            display_name="搜索岗位工具",
        )
        info = introspect_tool(tool)
        assert info["name"] == "search_jobs"
        assert info["display_name"] == "搜索岗位工具"
        assert info["description"] == "搜索岗位"
        assert info["category"] == "data"
        assert info["toolset"] == "core"
        assert info["concurrency_safe"] is True

    def test_parameters_extraction(self):
        schema = {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "city": {"type": "string", "description": "城市"},
                "limit": {"type": "integer", "description": "数量限制"},
            },
            "required": ["keyword"],
        }
        tool = DummyTool(name="query", parameters_schema=schema)
        info = introspect_tool(tool)
        params = info["parameters"]
        assert len(params) == 3
        kw_param = next(p for p in params if p["name"] == "keyword")
        assert kw_param["type"] == "string"
        assert kw_param["required"] is True
        assert kw_param["description"] == "搜索关键词"
        city_param = next(p for p in params if p["name"] == "city")
        assert city_param["required"] is False

    def test_empty_schema(self):
        tool = DummyTool(
            name="no_params",
            parameters_schema={"type": "object", "properties": {}, "required": []},
        )
        info = introspect_tool(tool)
        assert info["parameters"] == []

    def test_none_schema(self):
        """parameters_schema 为 None 时应安全处理"""
        tool = DummyTool(name="null_schema")
        tool._parameters_schema = None  # type: ignore
        info = introspect_tool(tool)
        assert info["parameters"] == []

    def test_enum_and_default_extraction(self):
        schema = {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "description": "平台",
                    "enum": ["boss", "liepin"],
                },
                "limit": {
                    "type": "integer",
                    "description": "数量",
                    "default": 10,
                },
            },
            "required": ["platform"],
        }
        tool = DummyTool(name="with_extras", parameters_schema=schema)
        info = introspect_tool(tool)
        platform_param = next(p for p in info["parameters"] if p["name"] == "platform")
        assert platform_param["enum"] == ["boss", "liepin"]
        limit_param = next(p for p in info["parameters"] if p["name"] == "limit")
        assert limit_param["default"] == 10

    def test_description_fallback(self):
        """description 为空时应回退到 '(无描述)'"""
        tool = DummyTool(name="no_desc")
        tool._description = ""
        info = introspect_tool(tool)
        assert info["description"] == "(无描述)"

    def test_default_display_name(self):
        """未设置 display_name 时应回退到 name"""
        tool = DummyTool(name="my_tool")
        # DummyTool default: display_name = name
        info = introspect_tool(tool)
        assert info["display_name"] == "my_tool"


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Valid tool names: lowercase + underscores, non-empty
st_tool_name = st.from_regex(r"[a-z][a-z0-9_]{0,19}", fullmatch=True)

# Non-empty descriptions (no pipe chars or backticks to avoid Markdown table issues)
st_description = (
    st.text(min_size=1, max_size=100)
    .map(lambda s: s.replace("|", " ").replace("`", " ").replace("\n", " ").replace("\r", " ").strip())
    .filter(lambda s: len(s) > 0)
)

# JSON Schema types
st_json_type = st.sampled_from(["string", "integer", "number", "boolean", "array", "object"])

# Categories used in the doc generator
st_category = st.sampled_from(["data", "memory", "getjob", "browser", "ai"])

# Toolsets
st_toolset = st.sampled_from(["core", "crawl", "admin", "deliver", "web"])

# Parameter name
st_param_name = st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True)

# Parameter description (no pipe/backtick/newline to keep Markdown table parseable)
st_param_desc = (
    st.text(min_size=1, max_size=50)
    .map(lambda s: s.replace("|", " ").replace("`", " ").replace("\n", " ").replace("\r", " ").strip())
    .filter(lambda s: len(s) > 0)
)


@st.composite
def st_parameters_schema(draw):
    """Generate a valid JSON Schema with 1..5 properties (non-empty for completeness tests)."""
    num_props = draw(st.integers(min_value=1, max_value=5))
    prop_names = draw(
        st.lists(st_param_name, min_size=num_props, max_size=num_props, unique=True)
    )
    properties = {}
    for pname in prop_names:
        properties[pname] = {
            "type": draw(st_json_type),
            "description": draw(st_param_desc),
        }
    required = draw(
        st.lists(
            st.sampled_from(prop_names),
            max_size=len(prop_names),
            unique=True,
        )
    )
    return {"type": "object", "properties": properties, "required": required}


@st.composite
def st_parameters_schema_maybe_empty(draw):
    """Generate a valid JSON Schema with 0..5 properties."""
    num_props = draw(st.integers(min_value=0, max_value=5))
    if num_props == 0:
        return {"type": "object", "properties": {}, "required": []}
    prop_names = draw(
        st.lists(st_param_name, min_size=num_props, max_size=num_props, unique=True)
    )
    properties = {}
    for pname in prop_names:
        properties[pname] = {
            "type": draw(st_json_type),
            "description": draw(st_param_desc),
        }
    required = draw(
        st.lists(
            st.sampled_from(prop_names),
            max_size=len(prop_names),
            unique=True,
        )
    )
    return {"type": "object", "properties": properties, "required": required}


@st.composite
def st_tool_config(draw):
    """Generate a complete tool configuration for PBT."""
    return {
        "name": draw(st_tool_name),
        "description": draw(st_description),
        "display_name": draw(st_description),
        "parameters_schema": draw(st_parameters_schema()),
        "category": draw(st_category),
        "toolset": draw(st_toolset),
        "concurrency_safe": draw(st.booleans()),
    }


@st.composite
def st_tool_config_maybe_empty_params(draw):
    """Generate a tool config that may have empty parameters."""
    return {
        "name": draw(st_tool_name),
        "description": draw(st_description),
        "display_name": draw(st_description),
        "parameters_schema": draw(st_parameters_schema_maybe_empty()),
        "category": draw(st_category),
        "toolset": draw(st_toolset),
        "concurrency_safe": draw(st.booleans()),
    }


def _make_tool(config: dict) -> DummyTool:
    """Create a DummyTool from a config dict."""
    return DummyTool(
        name=config["name"],
        description=config["description"],
        display_name=config["display_name"],
        parameters_schema=config["parameters_schema"],
        category=config["category"],
        toolset=config["toolset"],
        concurrency_safe=config["concurrency_safe"],
    )


# ---------------------------------------------------------------------------
# 3.2 [PBT] Property 1: Doc Generation Round-Trip
# ---------------------------------------------------------------------------


class TestDocGenerationRoundTrip:
    """
    # Feature: tools-api-docs-and-tests, Property 1: Doc Generation Round-Trip
    #
    # For any registered Tool with valid name, description, and parameters_schema,
    # introspecting the Tool into a structured dict, formatting it as Markdown,
    # then re-parsing the Markdown back into a structured dict SHALL produce an
    # equivalent dictionary.
    """

    @given(config=st_tool_config())
    @settings(max_examples=100)
    def test_introspect_format_parse_roundtrip(self, config: dict):
        """
        # Feature: tools-api-docs-and-tests, Property 1: Doc Generation Round-Trip
        introspect → format → parse produces equivalent dict.
        **Validates: Requirements 1.5**
        """
        tool = _make_tool(config)

        # Step 1: introspect
        tool_info = introspect_tool(tool)

        # Step 2: format to Markdown
        markdown = format_tool_section(tool_info)

        # Step 3: parse back from Markdown
        parsed = parse_tool_section(markdown)

        # Verify equivalence of core fields
        assert parsed["name"] == tool_info["name"]
        assert parsed["display_name"] == tool_info["display_name"]
        assert parsed["description"] == tool_info["description"]
        assert parsed["category"] == tool_info["category"]
        assert parsed["toolset"] == tool_info["toolset"]
        assert parsed["concurrency_safe"] == tool_info["concurrency_safe"]

        # Verify parameters match (name, type, required, description)
        assert len(parsed["parameters"]) == len(tool_info["parameters"])
        for orig, back in zip(tool_info["parameters"], parsed["parameters"]):
            assert back["name"] == orig["name"]
            assert back["type"] == orig["type"]
            assert back["required"] == orig["required"]
            # Description may have extra enum/default info appended, but base desc is present
            assert orig["description"] in back["description"]


# ---------------------------------------------------------------------------
# 3.3 [PBT] Property 2: Doc Section Completeness
# ---------------------------------------------------------------------------


class TestDocSectionCompleteness:
    """
    # Feature: tools-api-docs-and-tests, Property 2: Doc Section Completeness
    #
    # For any Tool with a non-empty parameters_schema containing N properties
    # (each with type and description), the generated Markdown section SHALL
    # contain: the tool name, display name, description, toolset, category,
    # concurrency safety flag, and a parameter table with exactly N rows where
    # each row includes the parameter name, its JSON Schema type, required
    # status, and description text.
    """

    @given(config=st_tool_config())
    @settings(max_examples=100)
    def test_section_contains_all_fields(self, config: dict):
        """
        # Feature: tools-api-docs-and-tests, Property 2: Doc Section Completeness
        Generated Markdown contains all required fields and N parameter rows.
        **Validates: Requirements 1.2, 2.2**
        """
        tool = _make_tool(config)
        tool_info = introspect_tool(tool)
        markdown = format_tool_section(tool_info)

        schema = config["parameters_schema"]
        properties = schema.get("properties", {})
        required_list = schema.get("required", [])
        n_params = len(properties)

        # Tool name appears in header
        assert f"`{config['name']}`" in markdown

        # Display name appears in header
        assert config["display_name"] in markdown

        # Description appears in blockquote
        expected_desc = config["description"] or "(无描述)"
        assert expected_desc in markdown

        # Category appears
        assert config["category"] in markdown

        # Toolset appears
        assert config["toolset"] in markdown

        # Concurrency flag appears
        if config["concurrency_safe"]:
            assert "✅ 是" in markdown
        else:
            assert "❌ 否" in markdown

        # Parameter table has exactly N rows
        param_row_pattern = re.compile(
            r"^\| `[^`]+` \| `[^`]+` \| (?:✅|) \| .* \|$", re.MULTILINE
        )
        param_rows = param_row_pattern.findall(markdown)
        assert len(param_rows) == n_params, (
            f"Expected {n_params} param rows, got {len(param_rows)}"
        )

        # Each parameter name, type, required status, and description present
        for param_name, prop in properties.items():
            assert f"`{param_name}`" in markdown
            assert f"`{prop['type']}`" in markdown
            # Required status
            if param_name in required_list:
                # Find the row for this param and check it has ✅
                row_pattern = re.compile(
                    rf"^\| `{re.escape(param_name)}` \| `[^`]+` \| ✅ \|",
                    re.MULTILINE,
                )
                assert row_pattern.search(markdown), (
                    f"Required param '{param_name}' should have ✅"
                )
            # Description text present in the row
            assert prop["description"] in markdown


# ---------------------------------------------------------------------------
# 3.4 [PBT] Property 3: Catalog Category Grouping
# ---------------------------------------------------------------------------


class TestCatalogCategoryGrouping:
    """
    # Feature: tools-api-docs-and-tests, Property 3: Catalog Category Grouping
    #
    # For any set of registered Tools with varying categories, the generated
    # Tool Catalog SHALL contain every registered tool name exactly once,
    # and each tool SHALL appear under a section heading matching its category.
    """

    @given(
        configs=st.lists(
            st_tool_config_maybe_empty_params(),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_catalog_contains_all_tools_grouped_by_category(self, configs: list[dict]):
        """
        # Feature: tools-api-docs-and-tests, Property 3: Catalog Category Grouping
        Catalog contains every tool exactly once under its category heading.
        **Validates: Requirements 1.3**
        """
        registry = ToolRegistry()

        # Deduplicate by name (last wins, matching register behavior)
        unique_configs: dict[str, dict] = {}
        for cfg in configs:
            unique_configs[cfg["name"]] = cfg

        for cfg in unique_configs.values():
            registry.register(_make_tool(cfg))

        catalog = generate_catalog(registry)

        # Every tool name appears exactly once (as `name` in a ### header)
        for name, cfg in unique_configs.items():
            # Count occurrences of the tool header pattern
            header_pattern = re.compile(
                rf"^### `{re.escape(name)}` — ", re.MULTILINE
            )
            matches = header_pattern.findall(catalog)
            assert len(matches) == 1, (
                f"Tool '{name}' should appear exactly once, found {len(matches)}"
            )

        # Each tool appears under its category section heading
        # Category sections use ## heading with category name
        from scripts.generate_tool_docs import _CATEGORY_NAMES

        for name, cfg in unique_configs.items():
            cat = cfg["category"]
            cat_display = _CATEGORY_NAMES.get(cat, cat)

            # Find the category section and verify tool is within it
            cat_heading_pattern = re.compile(
                rf"^## {re.escape(cat_display)}$", re.MULTILINE
            )
            cat_match = cat_heading_pattern.search(catalog)
            assert cat_match, (
                f"Category heading '{cat_display}' not found for tool '{name}'"
            )

            # Find the tool header
            tool_header_pattern = re.compile(
                rf"^### `{re.escape(name)}` — ", re.MULTILINE
            )
            tool_match = tool_header_pattern.search(catalog)
            assert tool_match

            # Tool should appear after its category heading
            # and before the next ## heading (or end of doc)
            cat_pos = cat_match.start()
            tool_pos = tool_match.start()
            assert tool_pos > cat_pos, (
                f"Tool '{name}' (pos {tool_pos}) should appear after "
                f"category '{cat_display}' (pos {cat_pos})"
            )

            # Find next ## heading after category
            next_section = re.search(
                r"^## ", catalog[cat_pos + 1:], re.MULTILINE
            )
            if next_section:
                next_section_pos = cat_pos + 1 + next_section.start()
                assert tool_pos < next_section_pos, (
                    f"Tool '{name}' (pos {tool_pos}) should appear before "
                    f"next section (pos {next_section_pos})"
                )
