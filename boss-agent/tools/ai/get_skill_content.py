"""
GetSkillContentTool — 允许 AI 在运行时按名称加载 Skill 完整内容

成功时返回 Skill 的完整场景参考内容（经 SKILL_DIR 变量替换）、
allowed-tools 列表、名称和描述。
失败时返回错误信息和所有可用 Skill 名称列表。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.tool_registry import Tool

if TYPE_CHECKING:
    from agent.skill_loader import SkillLoader


class GetSkillContentTool(Tool):
    """按 Skill 名称加载完整的场景参考内容。"""

    def __init__(self, skill_loader: SkillLoader) -> None:
        self._skill_loader = skill_loader

    @property
    def name(self) -> str:
        return "get_skill_content"

    @property
    def description(self) -> str:
        return (
            "按 Skill 名称加载完整的场景参考内容，"
            "包含详细的上下文信息、工具使用示例和典型流程参考"
        )

    @property
    def category(self) -> str:
        return "ai"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "要加载的 Skill 名称",
                },
            },
            "required": ["skill_name"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        skill_name = params.get("skill_name", "")
        result = self._skill_loader.get_skill_content(skill_name)

        if result is not None:
            return {
                "success": True,
                "name": result["name"],
                "description": result["description"],
                "content": result["content"],
                "allowed_tools": result["allowed_tools"],
            }

        return {
            "success": False,
            "error": f"Skill '{skill_name}' 未找到",
            "available_skills": self._skill_loader.get_all_skill_names(),
        }
