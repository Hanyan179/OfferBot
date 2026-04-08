"""Toolset 路由层 — 属性测试 (Property-Based Testing)

使用 Hypothesis 验证 ToolRegistry toolset 分组的正确性属性。
测试文件对应 .kiro/specs/toolset-routing/design.md 中的 Property 1-6。
"""

import asyncio
from typing import Any

from hypothesis import given, settings, strategies as st

from agent.tool_registry import Tool, ToolRegistry
from tools.meta.activate_toolset import ActivateToolsetTool, VALID_TOOLSETS


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class DummyTool(Tool):
    """测试用的具体 Tool 实现"""

    def __init__(self, name: str = "dummy", description: str | None = None):
        self._name = name
        self._description = description or f"A dummy tool named {name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, params: dict, context: Any) -> Any:
        return {}


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# 合法工具名
st_tool_name = st.from_regex(r"[a-z][a-z0-9_]{0,29}", fullmatch=True)

# 合法 toolset 名称
st_toolset = st.sampled_from(["core", "crawl", "deliver", "admin", "web", "sub_agent", "deprecated"])

# (tool_name, toolset) 对，保证 tool_name 唯一
st_tool_with_toolset = st.tuples(st_tool_name, st_toolset)

# toolset 名称子集
st_toolset_subset = st.sets(st_toolset)


@st.composite
def st_unique_tools_with_toolsets(draw, min_size=1, max_size=20):
    """生成一组 (tool_name, toolset) 对，tool_name 唯一。"""
    pairs = draw(
        st.lists(st_tool_with_toolset, min_size=min_size, max_size=max_size)
    )
    # 去重：同名工具保留最后一个
    seen: dict[str, str] = {}
    for name, ts in pairs:
        seen[name] = ts
    return list(seen.items())


def _register_tools(registry: ToolRegistry, pairs: list[tuple[str, str]]) -> None:
    """批量注册工具到 registry。"""
    for name, ts in pairs:
        registry.register(DummyTool(name=name), toolset=ts)


# ---------------------------------------------------------------------------
# Property 1: 工具集注册 round-trip
# Feature: toolset-routing, Property 1: 工具集注册 round-trip
# ---------------------------------------------------------------------------

class TestProperty1ToolsetRegistrationRoundTrip:
    """
    For any Tool 和任意 toolset 名称（或不指定 toolset），注册后通过
    get_tools_by_toolset() 查询应能找到该 Tool，且未指定 toolset 时应归入 deprecated。
    Validates: Requirements 1.1, 1.6
    """

    @given(data=st_unique_tools_with_toolsets(min_size=1, max_size=15))
    @settings(max_examples=100)
    def test_registered_tool_found_in_its_toolset(self, data: list[tuple[str, str]]):
        """# Feature: toolset-routing, Property 1: 注册后通过 get_tools_by_toolset 可找到"""
        reg = ToolRegistry()
        _register_tools(reg, data)

        for name, ts in data:
            tools_in_ts = reg.get_tools_by_toolset(ts)
            tool_names = {t.name for t in tools_in_ts}
            assert name in tool_names, (
                f"Tool '{name}' registered with toolset '{ts}' "
                f"not found in get_tools_by_toolset('{ts}')"
            )

    @given(name=st_tool_name)
    @settings(max_examples=100)
    def test_unspecified_toolset_defaults_to_deprecated(self, name: str):
        """# Feature: toolset-routing, Property 1: 未指定 toolset 归入 deprecated"""
        reg = ToolRegistry()
        reg.register(DummyTool(name=name))  # 不传 toolset，使用默认值

        tools = reg.get_tools_by_toolset("deprecated")
        assert any(t.name == name for t in tools)

    @given(name=st_tool_name)
    @settings(max_examples=100)
    def test_empty_string_toolset_defaults_to_deprecated(self, name: str):
        """# Feature: toolset-routing, Property 1: 空字符串 toolset 归入 deprecated"""
        reg = ToolRegistry()
        reg.register(DummyTool(name=name), toolset="")

        tools = reg.get_tools_by_toolset("deprecated")
        assert any(t.name == name for t in tools)


# ---------------------------------------------------------------------------
# Property 2: Schema 过滤精确性
# Feature: toolset-routing, Property 2: Schema 过滤精确性
# ---------------------------------------------------------------------------

class TestProperty2SchemaFilterPrecision:
    """
    For any 一组已注册的 Tool（分属不同 toolset），以及任意 toolset 名称子集，
    get_schemas_for_toolsets(subset) 返回的 Schema 集合应恰好等于属于这些 toolset
    的 Tool 的 Schema 集合——不多不少。
    Validates: Requirements 1.3
    """

    @given(
        data=st_unique_tools_with_toolsets(min_size=1, max_size=15),
        query_toolsets=st_toolset_subset,
    )
    @settings(max_examples=100)
    def test_schema_filter_returns_exact_match(
        self, data: list[tuple[str, str]], query_toolsets: set[str]
    ):
        """# Feature: toolset-routing, Property 2: Schema 过滤精确性"""
        reg = ToolRegistry()
        _register_tools(reg, data)

        # 预期：属于 query_toolsets 中任一 toolset 的工具名集合
        expected_names = {name for name, ts in data if ts in query_toolsets}

        schemas = reg.get_schemas_for_toolsets(query_toolsets)
        actual_names = {s["function"]["name"] for s in schemas}

        assert actual_names == expected_names, (
            f"query_toolsets={query_toolsets}, "
            f"expected={expected_names}, actual={actual_names}"
        )

    @given(data=st_unique_tools_with_toolsets(min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_empty_toolset_query_returns_empty(self, data: list[tuple[str, str]]):
        """# Feature: toolset-routing, Property 2: 空集合返回空列表"""
        reg = ToolRegistry()
        _register_tools(reg, data)

        schemas = reg.get_schemas_for_toolsets(set())
        assert schemas == []


# ---------------------------------------------------------------------------
# Property 3: get_all_schemas 向后兼容
# Feature: toolset-routing, Property 3: get_all_schemas 向后兼容
# ---------------------------------------------------------------------------

class TestProperty3GetAllSchemasBackwardCompat:
    """
    For any 一组已注册的 Tool（分属不同 toolset），get_all_schemas() 返回的
    Schema 数量应等于所有已注册 Tool 的数量，与 toolset 分组无关。
    Validates: Requirements 1.4
    """

    @given(data=st_unique_tools_with_toolsets(min_size=0, max_size=20))
    @settings(max_examples=100)
    def test_all_schemas_count_equals_tool_count(self, data: list[tuple[str, str]]):
        """# Feature: toolset-routing, Property 3: Schema 数量等于注册 Tool 数量"""
        reg = ToolRegistry()
        _register_tools(reg, data)

        schemas = reg.get_all_schemas()
        assert len(schemas) == len(data)

    @given(data=st_unique_tools_with_toolsets(min_size=1, max_size=15))
    @settings(max_examples=100)
    def test_all_schemas_names_match_registered(self, data: list[tuple[str, str]]):
        """# Feature: toolset-routing, Property 3: Schema 名称集合等于注册名称集合"""
        reg = ToolRegistry()
        _register_tools(reg, data)

        schema_names = {s["function"]["name"] for s in reg.get_all_schemas()}
        registered_names = {name for name, _ in data}
        assert schema_names == registered_names


# ---------------------------------------------------------------------------
# Property 4: list_toolsets 一致性
# Feature: toolset-routing, Property 4: list_toolsets 一致性
# ---------------------------------------------------------------------------

class TestProperty4ListToolsetsConsistency:
    """
    For any 一组已注册的 Tool，list_toolsets() 返回的 toolset 名称集合应恰好等于
    注册时使用过的 toolset 名称集合。
    Validates: Requirements 1.5
    """

    @given(data=st_unique_tools_with_toolsets(min_size=1, max_size=15))
    @settings(max_examples=100)
    def test_list_toolsets_matches_registered_toolsets(self, data: list[tuple[str, str]]):
        """# Feature: toolset-routing, Property 4: list_toolsets 一致性"""
        reg = ToolRegistry()
        _register_tools(reg, data)

        expected_toolsets = {ts for _, ts in data}
        actual_toolsets = set(reg.list_toolsets())
        assert actual_toolsets == expected_toolsets

    def test_empty_registry_returns_no_toolsets(self):
        """# Feature: toolset-routing, Property 4: 空 registry 无 toolset"""
        reg = ToolRegistry()
        assert reg.list_toolsets() == []


# ---------------------------------------------------------------------------
# Helpers for async tool execution
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# Strategy: 非法 toolset 名称（不在 VALID_TOOLSETS 中的任意字符串）
st_invalid_toolset_name = st.text(min_size=1, max_size=30).filter(
    lambda s: s not in VALID_TOOLSETS
)

# Strategy: 合法 toolset 名称
st_valid_toolset_name = st.sampled_from(sorted(VALID_TOOLSETS))


# ---------------------------------------------------------------------------
# Property 5: activate_toolset 幂等性
# Feature: toolset-routing, Property 5: activate_toolset 幂等性
# ---------------------------------------------------------------------------

class TestProperty5ActivateToolsetIdempotency:
    """
    For any 合法的 toolset 名称，连续两次调用 activate_toolset 应都返回成功，
    第二次应标注 already_active=True，且 active_toolsets 集合中该 toolset 只出现一次。
    Validates: Requirements 2.2, 2.4
    """

    @given(toolset_name=st_valid_toolset_name)
    @settings(max_examples=100)
    def test_first_activation_succeeds(self, toolset_name: str):
        """# Feature: toolset-routing, Property 5: 首次激活成功"""
        tool = ActivateToolsetTool()
        context: dict[str, Any] = {"active_toolsets": {"core"}}

        result = _run_async(tool.execute({"name": toolset_name}, context))

        assert result["success"] is True
        assert result["already_active"] is False
        assert toolset_name in context["active_toolsets"]

    @given(toolset_name=st_valid_toolset_name)
    @settings(max_examples=100)
    def test_second_activation_marks_already_active(self, toolset_name: str):
        """# Feature: toolset-routing, Property 5: 第二次激活标注 already_active"""
        tool = ActivateToolsetTool()
        context: dict[str, Any] = {"active_toolsets": {"core"}}

        # 第一次
        result1 = _run_async(tool.execute({"name": toolset_name}, context))
        assert result1["success"] is True
        assert result1["already_active"] is False

        # 第二次
        result2 = _run_async(tool.execute({"name": toolset_name}, context))
        assert result2["success"] is True
        assert result2["already_active"] is True

    @given(toolset_name=st_valid_toolset_name)
    @settings(max_examples=100)
    def test_idempotent_no_duplicate_in_set(self, toolset_name: str):
        """# Feature: toolset-routing, Property 5: 幂等——集合中不重复"""
        tool = ActivateToolsetTool()
        context: dict[str, Any] = {"active_toolsets": {"core"}}

        _run_async(tool.execute({"name": toolset_name}, context))
        _run_async(tool.execute({"name": toolset_name}, context))

        # set 天然去重，但验证 active_toolsets 仍是 set 且只含一次
        active = context["active_toolsets"]
        assert isinstance(active, set)
        count = list(active).count(toolset_name)
        assert count == 1


# ---------------------------------------------------------------------------
# Property 6: activate_toolset 非法名称拒绝
# Feature: toolset-routing, Property 6: activate_toolset 非法名称拒绝
# ---------------------------------------------------------------------------

class TestProperty6ActivateToolsetInvalidNameRejection:
    """
    For any 不在 {crawl, deliver, admin, web} 中的字符串，调用 activate_toolset
    应返回 success=False 且 active_toolsets 不变。
    Validates: Requirements 2.3
    """

    @given(invalid_name=st_invalid_toolset_name)
    @settings(max_examples=100)
    def test_invalid_name_returns_failure(self, invalid_name: str):
        """# Feature: toolset-routing, Property 6: 非法名称返回 success=False"""
        tool = ActivateToolsetTool()
        context: dict[str, Any] = {"active_toolsets": {"core"}}

        result = _run_async(tool.execute({"name": invalid_name}, context))

        assert result["success"] is False
        assert "error" in result

    @given(invalid_name=st_invalid_toolset_name)
    @settings(max_examples=100)
    def test_invalid_name_does_not_modify_active_toolsets(self, invalid_name: str):
        """# Feature: toolset-routing, Property 6: 非法名称不改变 active_toolsets"""
        tool = ActivateToolsetTool()
        original_active = {"core"}
        context: dict[str, Any] = {"active_toolsets": original_active.copy()}

        _run_async(tool.execute({"name": invalid_name}, context))

        assert context["active_toolsets"] == original_active

    @given(
        invalid_name=st_invalid_toolset_name,
        pre_activated=st.sets(st_valid_toolset_name, min_size=0, max_size=3),
    )
    @settings(max_examples=100)
    def test_invalid_name_preserves_existing_activations(
        self, invalid_name: str, pre_activated: set[str]
    ):
        """# Feature: toolset-routing, Property 6: 非法名称保留已有激活状态"""
        tool = ActivateToolsetTool()
        active = {"core"} | pre_activated
        context: dict[str, Any] = {"active_toolsets": active.copy()}

        _run_async(tool.execute({"name": invalid_name}, context))

        assert context["active_toolsets"] == active


# ---------------------------------------------------------------------------
# Strategies for Property 7-8
# ---------------------------------------------------------------------------

# Toolsets that users/LLM can activate (never includes sub_agent or deprecated)
st_user_facing_toolset = st.sampled_from(["core", "crawl", "deliver", "admin", "web"])
st_user_facing_toolset_subset = st.sets(st_user_facing_toolset, min_size=1, max_size=5)

HIDDEN_TOOLSETS = {"sub_agent", "deprecated"}


@st.composite
def st_registry_with_hidden_tools(draw, min_visible=2, max_visible=10, min_hidden=1, max_hidden=6):
    """生成一个 ToolRegistry，包含可见工具集和隐藏工具集（sub_agent/deprecated）的工具。

    返回 (registry, visible_pairs, hidden_pairs)。
    """
    visible_toolsets = ["core", "crawl", "deliver", "admin", "web"]
    hidden_toolsets = ["sub_agent", "deprecated"]

    visible_pairs = draw(st.lists(
        st.tuples(st_tool_name, st.sampled_from(visible_toolsets)),
        min_size=min_visible, max_size=max_visible,
    ))
    hidden_pairs = draw(st.lists(
        st.tuples(st_tool_name, st.sampled_from(hidden_toolsets)),
        min_size=min_hidden, max_size=max_hidden,
    ))

    # 去重：所有名称唯一
    seen: dict[str, str] = {}
    for name, ts in visible_pairs + hidden_pairs:
        seen[name] = ts
    visible_pairs = [(n, t) for n, t in seen.items() if t in visible_toolsets]
    hidden_pairs = [(n, t) for n, t in seen.items() if t in hidden_toolsets]

    reg = ToolRegistry()
    for name, ts in visible_pairs + hidden_pairs:
        reg.register(DummyTool(name=name), toolset=ts)

    return reg, visible_pairs, hidden_pairs


# ---------------------------------------------------------------------------
# Property 7: sub_agent 工具隔离
# Feature: toolset-routing, Property 7: sub_agent 工具隔离
# ---------------------------------------------------------------------------

class TestProperty7SubAgentToolIsolation:
    """
    For any active_toolsets 组合（不含 sub_agent 和 deprecated），
    get_schemas_for_toolsets(active_toolsets) 返回的 Schema 中不应包含
    sub_agent 或 deprecated 工具集的 Tool。
    Validates: Requirements 6.3
    """

    @given(
        data=st_registry_with_hidden_tools(),
        active=st_user_facing_toolset_subset,
    )
    @settings(max_examples=100)
    def test_hidden_tools_never_in_user_facing_schemas(
        self,
        data: tuple[ToolRegistry, list[tuple[str, str]], list[tuple[str, str]]],
        active: set[str],
    ):
        """# Feature: toolset-routing, Property 7: 隐藏工具不出现在用户可见 Schema 中"""
        reg, _visible_pairs, hidden_pairs = data
        hidden_names = {name for name, _ in hidden_pairs}

        schemas = reg.get_schemas_for_toolsets(active)
        schema_names = {s["function"]["name"] for s in schemas}

        leaked = schema_names & hidden_names
        assert not leaked, (
            f"active_toolsets={active}, hidden tools leaked into schemas: {leaked}"
        )

    @given(data=st_registry_with_hidden_tools())
    @settings(max_examples=100)
    def test_hidden_toolsets_excluded_from_any_single_user_toolset(
        self,
        data: tuple[ToolRegistry, list[tuple[str, str]], list[tuple[str, str]]],
    ):
        """# Feature: toolset-routing, Property 7: 逐个用户工具集都不含隐藏工具"""
        reg, _visible_pairs, hidden_pairs = data
        hidden_names = {name for name, _ in hidden_pairs}

        for ts in ["core", "crawl", "deliver", "admin", "web"]:
            schemas = reg.get_schemas_for_toolsets({ts})
            schema_names = {s["function"]["name"] for s in schemas}
            leaked = schema_names & hidden_names
            assert not leaked, (
                f"toolset='{ts}' contains hidden tools: {leaked}"
            )


# ---------------------------------------------------------------------------
# Property 8: sub_agent 工具可达性
# Feature: toolset-routing, Property 8: sub_agent 工具可达性
# ---------------------------------------------------------------------------

class TestProperty8SubAgentToolReachability:
    """
    For any 注册在 sub_agent 工具集中的 Tool，通过 get_tool(name) 仍应能获取到
    该 Tool 实例。
    Validates: Requirements 6.4
    """

    @given(data=st_registry_with_hidden_tools())
    @settings(max_examples=100)
    def test_hidden_tools_reachable_via_get_tool(
        self,
        data: tuple[ToolRegistry, list[tuple[str, str]], list[tuple[str, str]]],
    ):
        """# Feature: toolset-routing, Property 8: 隐藏工具可通过 get_tool 获取"""
        reg, _visible_pairs, hidden_pairs = data

        for name, _ts in hidden_pairs:
            tool = reg.get_tool(name)
            assert tool is not None, (
                f"Tool '{name}' in hidden toolset should be reachable via get_tool()"
            )
            assert tool.name == name

    @given(data=st_registry_with_hidden_tools())
    @settings(max_examples=100)
    def test_sub_agent_tools_reachable_but_not_in_user_schemas(
        self,
        data: tuple[ToolRegistry, list[tuple[str, str]], list[tuple[str, str]]],
    ):
        """# Feature: toolset-routing, Property 8: sub_agent 工具可达但不在用户 Schema 中"""
        reg, _visible_pairs, hidden_pairs = data
        sub_agent_names = {name for name, ts in hidden_pairs if ts == "sub_agent"}

        # 可通过 get_tool 获取
        for name in sub_agent_names:
            assert reg.get_tool(name) is not None

        # 但不在任何用户可见工具集的 Schema 中
        all_user_schemas = reg.get_schemas_for_toolsets({"core", "crawl", "deliver", "admin", "web"})
        user_schema_names = {s["function"]["name"] for s in all_user_schemas}
        leaked = user_schema_names & sub_agent_names
        assert not leaked, f"sub_agent tools leaked: {leaked}"
