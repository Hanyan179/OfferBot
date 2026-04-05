"""
Property-Based Tests: Tool display_name 查询一致性

Feature: framework-core-fixes, Property 5: Tool display_name 查询一致性
Validates: Requirements 5.1, 5.3

使用 Hypothesis 生成随机 tool_name + display_name，验证注册后
get_display_name 返回一致。
"""

from __future__ import annotations

from typing import Any

import hypothesis.strategies as st
from hypothesis import given, settings

from agent.tool_registry import Tool, ToolRegistry


# ---------------------------------------------------------------------------
# Helper: 可配置 display_name 的 DummyTool
# ---------------------------------------------------------------------------

class _DummyTool(Tool):
    """测试用 Tool，支持自定义 display_name。"""

    def __init__(self, name: str, display_name: str | None = None) -> None:
        self._name = name
        self._display_name = display_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return self._display_name if self._display_name is not None else self.name

    @property
    def description(self) -> str:
        return f"dummy {self._name}"

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, params: dict, context: Any) -> Any:
        return None


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# tool_name: 非空可打印字符串（模拟真实 tool 名称）
st_tool_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=50,
)

# display_name: 非空字符串（可包含中文等 Unicode）
st_display_name = st.text(min_size=1, max_size=100)


# ---------------------------------------------------------------------------
# Property 5: Tool display_name 查询一致性
# ---------------------------------------------------------------------------

class TestToolDisplayNameProperty:
    """Feature: framework-core-fixes, Property 5: Tool display_name 查询一致性"""

    @given(tool_name=st_tool_name, display_name=st_display_name)
    @settings(max_examples=200)
    def test_get_display_name_returns_custom_display_name(
        self, tool_name: str, display_name: str
    ) -> None:
        """注册带自定义 display_name 的 Tool 后，get_display_name 应返回该值。"""
        registry = ToolRegistry()
        tool = _DummyTool(name=tool_name, display_name=display_name)
        registry.register(tool)

        assert registry.get_display_name(tool_name) == display_name

    @given(tool_name=st_tool_name)
    @settings(max_examples=200)
    def test_get_display_name_falls_back_to_name(self, tool_name: str) -> None:
        """未设置 display_name 的 Tool，get_display_name 应回退返回 name。"""
        registry = ToolRegistry()
        tool = _DummyTool(name=tool_name)  # display_name=None → 回退到 name
        registry.register(tool)

        assert registry.get_display_name(tool_name) == tool_name

    @given(tool_name=st_tool_name)
    @settings(max_examples=200)
    def test_get_display_name_unknown_tool_returns_input(
        self, tool_name: str
    ) -> None:
        """查询未注册的 tool_name 时，get_display_name 应返回传入的原值。"""
        registry = ToolRegistry()

        assert registry.get_display_name(tool_name) == tool_name
