"""GetSkillContentTool 单元测试

验证:
- 成功返回完整内容（需求 7.3）
- 失败返回可用 Skill 列表（需求 7.4）
- 注册到 ToolRegistry 后可被发现（需求 7.2）
"""

from __future__ import annotations

import pytest

from agent.skill_loader import SkillLoader
from agent.tool_registry import ToolRegistry
from tools.ai.get_skill_content import GetSkillContentTool


def _make_skill(tmp_path, folder_name: str, content: str):
    folder = tmp_path / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(content, encoding="utf-8")


class TestGetSkillContentToolSuccess:
    """成功返回完整内容"""

    @pytest.mark.asyncio
    async def test_returns_success_with_all_fields(self, tmp_path):
        _make_skill(
            tmp_path, "resume",
            "---\nname: 简历生成\ndescription: 生成简历\n"
            "allowed-tools: [get_memory]\n---\n## 场景描述\n简历内容",
        )
        loader = SkillLoader(str(tmp_path))
        loader.load_all()
        tool = GetSkillContentTool(loader)

        result = await tool.execute({"skill_name": "简历生成"}, context=None)

        assert result["success"] is True
        assert result["name"] == "简历生成"
        assert result["description"] == "生成简历"
        assert "简历内容" in result["content"]
        assert result["allowed_tools"] == ["get_memory"]

    @pytest.mark.asyncio
    async def test_skill_dir_replaced_in_content(self, tmp_path):
        _make_skill(
            tmp_path, "myskill",
            "---\nname: My\n---\n## 场景描述\n路径: ${SKILL_DIR}/tpl.txt",
        )
        loader = SkillLoader(str(tmp_path))
        loader.load_all()
        tool = GetSkillContentTool(loader)

        result = await tool.execute({"skill_name": "My"}, context=None)

        assert result["success"] is True
        assert "${SKILL_DIR}" not in result["content"]
        assert str((tmp_path / "myskill").resolve()) in result["content"]


class TestGetSkillContentToolFailure:
    """失败返回可用 Skill 列表"""

    @pytest.mark.asyncio
    async def test_returns_failure_with_available_skills(self, tmp_path):
        _make_skill(tmp_path, "a", "---\nname: Alpha\n---\n## 场景描述\n")
        _make_skill(tmp_path, "b", "---\nname: Beta\n---\n## 场景描述\n")
        loader = SkillLoader(str(tmp_path))
        loader.load_all()
        tool = GetSkillContentTool(loader)

        result = await tool.execute({"skill_name": "不存在"}, context=None)

        assert result["success"] is False
        assert "不存在" in result["error"]
        assert set(result["available_skills"]) == {"Alpha", "Beta"}

    @pytest.mark.asyncio
    async def test_empty_skill_name(self, tmp_path):
        _make_skill(tmp_path, "s", "---\nname: S\n---\n## 场景描述\n")
        loader = SkillLoader(str(tmp_path))
        loader.load_all()
        tool = GetSkillContentTool(loader)

        result = await tool.execute({"skill_name": ""}, context=None)

        assert result["success"] is False
        assert "available_skills" in result


class TestGetSkillContentToolRegistration:
    """注册到 ToolRegistry 后可被发现"""

    def test_tool_properties(self):
        loader = SkillLoader("/tmp/nonexistent")
        tool = GetSkillContentTool(loader)
        assert tool.name == "get_skill_content"
        assert tool.category == "ai"
        assert tool.is_concurrency_safe is True
        assert "skill_name" in tool.parameters_schema["properties"]

    def test_registered_in_registry(self):
        registry = ToolRegistry()
        loader = SkillLoader("/tmp/nonexistent")
        tool = GetSkillContentTool(loader)
        registry.register(tool)

        assert registry.has_tool("get_skill_content")
        assert registry.get_tool("get_skill_content") is tool

    def test_schema_in_all_schemas(self):
        registry = ToolRegistry()
        loader = SkillLoader("/tmp/nonexistent")
        registry.register(GetSkillContentTool(loader))

        schemas = registry.get_all_schemas()
        names = {s["function"]["name"] for s in schemas}
        assert "get_skill_content" in names
