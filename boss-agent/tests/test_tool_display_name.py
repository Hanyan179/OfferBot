"""
单元测试：验证所有已注册 Tool 都有非空中文 display_name。

测试文件: tests/test_tool_display_name.py
需求: 5.1
"""

from __future__ import annotations

import re

import pytest

from agent.bootstrap import create_tool_registry


@pytest.fixture(scope="module")
def registry():
    """创建包含所有已注册 Tool 的 registry。"""
    reg, _ = create_tool_registry()
    return reg


# 匹配至少包含一个中文字符的正则
_HAS_CHINESE = re.compile(r"[\u4e00-\u9fff]")


class TestAllToolsHaveDisplayName:
    """验证所有已注册 Tool 都有非空 display_name。"""

    def test_registry_not_empty(self, registry):
        """确保 registry 中有 Tool 注册。"""
        assert registry.tool_count > 0

    def test_all_tools_have_non_empty_display_name(self, registry):
        """每个 Tool 的 display_name 必须非空。"""
        for name in registry.list_tool_names():
            tool = registry.get_tool(name)
            assert tool is not None
            dn = tool.display_name
            assert isinstance(dn, str) and len(dn.strip()) > 0, (
                f"Tool '{name}' has empty display_name"
            )

    def test_all_tools_have_chinese_display_name(self, registry):
        """每个 Tool 的 display_name 必须包含中文字符。"""
        for name in registry.list_tool_names():
            tool = registry.get_tool(name)
            assert tool is not None
            dn = tool.display_name
            assert _HAS_CHINESE.search(dn), (
                f"Tool '{name}' display_name '{dn}' does not contain Chinese characters"
            )

    def test_display_name_differs_from_name(self, registry):
        """每个 Tool 的 display_name 应与英文 name 不同（说明已覆盖默认值）。"""
        for name in registry.list_tool_names():
            tool = registry.get_tool(name)
            assert tool is not None
            assert tool.display_name != tool.name, (
                f"Tool '{name}' display_name is same as name (default not overridden)"
            )

    def test_get_display_name_consistency(self, registry):
        """registry.get_display_name() 与 tool.display_name 一致。"""
        for name in registry.list_tool_names():
            tool = registry.get_tool(name)
            assert tool is not None
            assert registry.get_display_name(name) == tool.display_name
