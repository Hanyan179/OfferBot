"""
Tool 基类和 ToolRegistry 工具注册中心

定义 Tool 抽象基类（所有 Tool 必须实现此接口）和
ToolRegistry（统一管理 Tool 的注册、发现、调用）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Tool 基类，所有 Tool 必须实现此接口。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool 唯一名称"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool 功能描述"""
        ...

    @property
    @abstractmethod
    def parameters_schema(self) -> dict:
        """JSON Schema 格式的参数定义"""
        ...

    @property
    def display_name(self) -> str:
        """Tool 中文显示名，默认回退到 name"""
        return self.name

    @property
    def is_concurrency_safe(self) -> bool:
        """是否可并发执行（只读 Tool 返回 True）"""
        return False

    @property
    def category(self) -> str:
        """Tool 分类，用于 get_tools_by_category 查询"""
        return "general"

    @property
    def toolset(self) -> str:
        """Tool 所属工具集，用于动态 toolset 路由。默认 core（始终可见）。"""
        return "core"

    @abstractmethod
    async def execute(self, params: dict, context: Any) -> Any:
        """
        执行 Tool。

        Args:
            params: 调用参数，符合 parameters_schema 定义。
            context: Agent 上下文对象。

        Returns:
            ToolResult 对象。
        """
        ...


class ToolRegistry:
    """
    工具注册中心，统一管理 Tool 的注册、发现、调用。
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool, *, allow_overwrite: bool = True) -> None:
        """注册 Tool。

        Args:
            tool: 要注册的 Tool 实例。
            allow_overwrite: 是否允许覆盖同名 Tool。为 False 时重复注册抛出 ValueError。
        """
        if not allow_overwrite and tool.name in self._tools:
            raise ValueError(
                f"Tool '{tool.name}' is already registered. "
                "Use allow_overwrite=True to replace it."
            )
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Tool | None:
        """按名称获取 Tool，不存在返回 None。"""
        return self._tools.get(name)

    def get_all_schemas(self) -> list[dict]:
        """
        返回所有 Tool 的 JSON Schema，用于 LLM Function Calling。

        返回格式符合 OpenAI / DashScope Function Calling 协议：
        [
            {
                "type": "function",
                "function": {
                    "name": "<tool_name>",
                    "description": "<tool_description>",
                    "parameters": { ... JSON Schema ... }
                }
            },
            ...
        ]
        """
        schemas: list[dict] = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                },
            })
        return schemas

    def get_display_name(self, tool_name: str) -> str:
        """获取 Tool 的中文显示名，不存在时回退到 tool_name。"""
        tool = self._tools.get(tool_name)
        return tool.display_name if tool else tool_name

    def get_tools_by_category(self, category: str) -> list[Tool]:
        """按分类获取 Tool 列表。"""
        return [t for t in self._tools.values() if t.category == category]

    def list_tool_names(self) -> list[str]:
        """返回所有已注册 Tool 的名称列表。"""
        return list(self._tools.keys())

    @property
    def tool_count(self) -> int:
        """已注册 Tool 数量。"""
        return len(self._tools)

    def has_tool(self, name: str) -> bool:
        """检查是否已注册指定名称的 Tool。"""
        return name in self._tools

    def get_tools_by_toolset(self, toolset: str) -> list[Tool]:
        """返回属于指定 toolset 的所有 Tool。"""
        return [t for t in self._tools.values() if t.toolset == toolset]

    def get_schemas_for_toolsets(self, active_toolsets: set[str]) -> list[dict]:
        """返回属于 active_toolsets 中任一 toolset 的 Tool 的 JSON Schema 列表。"""
        schemas: list[dict] = []
        for tool in self._tools.values():
            if tool.toolset in active_toolsets:
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters_schema,
                    },
                })
        return schemas

    def validate_tool_names(self, names: list[str]) -> list[str]:
        """验证工具名列表，返回未注册的名称列表。"""
        return [n for n in names if n not in self._tools]

    def unregister(self, name: str) -> bool:
        """注销 Tool，返回是否成功（Tool 不存在时返回 False）。"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False
