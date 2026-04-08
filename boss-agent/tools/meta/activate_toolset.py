"""
activate_toolset 元工具

LLM 通过此工具按需激活场景工具集，使对应工具在下一轮 Function Calling 中可见。
"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool


VALID_TOOLSETS = frozenset({"crawl", "deliver", "admin", "web"})


class ActivateToolsetTool(Tool):
    """激活场景工具集的元工具。"""

    @property
    def name(self) -> str:
        return "activate_toolset"

    @property
    def display_name(self) -> str:
        return "激活工具集"

    @property
    def description(self) -> str:
        return (
            "激活场景工具集，使 LLM 可以使用该场景的工具。\n\n"
            "可用工具集：\n"
            "- crawl: 数据采集（爬取岗位列表、获取 JD 详情、同步数据）\n"
            "- deliver: 岗位投递（投递岗位、记录投递）\n"
            "- admin: 平台管理（配置、服务管理、统计）\n"
            "- web: 网页工具（抓取网页、搜索引擎）\n\n"
            "当核心工具不够用时调用此工具加载场景工具集。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "enum": ["crawl", "deliver", "admin", "web"],
                    "description": "要激活的工具集名称",
                }
            },
            "required": ["name"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        toolset_name = params["name"]

        if toolset_name not in VALID_TOOLSETS:
            return {
                "success": False,
                "error": f"未知工具集 '{toolset_name}'，可用: {sorted(VALID_TOOLSETS)}",
            }

        active: set = context.get("active_toolsets", {"core"})
        already_active = toolset_name in active
        active.add(toolset_name)
        context["active_toolsets"] = active

        # 从 registry 获取该 toolset 的工具名列表
        registry = context.get("registry")
        tool_names: list[str] = []
        if registry:
            tool_names = [t.name for t in registry.get_tools_by_toolset(toolset_name)]

        return {
            "success": True,
            "toolset": toolset_name,
            "already_active": already_active,
            "tools": tool_names,
            "message": (
                f"已激活 {toolset_name} 工具集"
                + ("（已处于激活状态）" if already_active else "")
            ),
        }
