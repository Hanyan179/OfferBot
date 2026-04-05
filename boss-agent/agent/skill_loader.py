"""
Skills 加载器 — 加载文件夹格式的 Skill 并生成 System Prompt 注入段落

架构升级：从扁平文件格式（skills/*.md）升级为文件夹格式（skills/skill-name/SKILL.md）。
每个 Skill 是一个自包含的文件夹，包含 SKILL.md 主文件和可选的资源文件。

核心理念：Skill 是场景参考规范，为 AI 提供上下文和示例，AI 自主决断。
- System Prompt 只注入摘要（name/description/when_to_use/allowed-tools），节省 token
- 完整内容通过 get_skill_content 按需加载
- 支持条件激活（paths 字段）和 ${SKILL_DIR} 变量替换
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from agent.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

SKILLS_DIR = str(Path(__file__).resolve().parent.parent / "skills")


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """
    解析 Markdown 文件的 YAML frontmatter。

    Returns:
        (frontmatter_dict, markdown_body)
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    try:
        fm = yaml.safe_load(parts[1])
        if not isinstance(fm, dict):
            return {}, content
        return fm, parts[2].strip()
    except yaml.YAMLError as e:
        logger.warning("YAML frontmatter 解析失败: %s", e)
        return {}, content


@dataclass
class SkillInfo:
    """Skill 元数据和内容的结构化表示。"""

    name: str                                       # 显示名称
    description: str                                # 简短描述
    when_to_use: str                                # 适用场景
    memory_categories: list[str] = field(default_factory=list)  # 记忆分类列表
    allowed_tools: list[str] = field(default_factory=list)      # 场景相关工具列表
    folder_name: str = ""                           # 文件夹名称（标识符）
    folder_path: str = ""                           # 文件夹绝对路径
    body: str = ""                                  # Markdown 正文
    is_conditional: bool = False                    # 是否为条件激活 Skill
    paths: list[str] | None = None                  # 条件激活路径模式（glob）


def _extract_first_paragraph(body: str) -> str:
    """从 Markdown 正文中提取第一段非空文本作为描述。"""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


class SkillLoader:
    """
    加载 skills/ 目录下的文件夹格式 Skill。

    每个 Skill 是一个子文件夹，包含 SKILL.md 主文件。
    SKILL.md 的 frontmatter 包含：
    - name: Skill 名称
    - description: 简短描述
    - when_to_use: 何时使用
    - memory_categories: 需要读取的记忆分类列表
    - allowed-tools: 允许使用的工具列表
    - paths: 条件激活路径模式列表（可选）
    """

    def __init__(
        self,
        skills_dir: str | None = None,
        registry: ToolRegistry | None = None,
    ):
        """
        Args:
            skills_dir: skills 目录路径，默认 boss-agent/skills/
            registry: ToolRegistry 实例，用于验证 allowed-tools
        """
        self.skills_dir = Path(skills_dir or SKILLS_DIR)
        self._registry = registry
        self._skills: list[SkillInfo] = []

    def load_all(self) -> list[SkillInfo]:
        """扫描 skills/ 下的子文件夹，解析每个 SKILL.md。

        - 跳过非文件夹的 .md 文件（记录警告）
        - 跳过无 SKILL.md 的文件夹（不记录日志）
        - 跳过 YAML 格式无效的文件（记录错误）
        - 验证 allowed-tools 中的工具是否已注册（记录警告）
        - 检查正文是否包含"场景描述"段落（记录警告）

        Returns:
            list[SkillInfo]
        """
        if not self.skills_dir.exists():
            self._skills = []
            return []

        # 警告散落的 .md 文件
        for item in sorted(self.skills_dir.iterdir()):
            if item.is_file() and item.suffix == ".md":
                logger.warning("跳过散落的 Skill 文件 %s，请迁移到文件夹格式", item.name)

        skills: list[SkillInfo] = []
        for folder in sorted(self.skills_dir.iterdir()):
            if not folder.is_dir():
                continue

            skill_md = folder / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                content = skill_md.read_text(encoding="utf-8")
            except Exception as e:
                logger.error("读取 Skill 文件夹 '%s' 的 SKILL.md 失败: %s", folder.name, e)
                continue

            fm, body = _parse_frontmatter(content)

            # 如果整个文件都没有有效 frontmatter 且 YAML 解析失败，
            # _parse_frontmatter 返回空 dict。但我们需要区分"无 frontmatter"和"YAML 无效"。
            # 对于 YAML 无效的情况，_parse_frontmatter 内部已记录 warning，
            # 这里额外检查：如果文件以 --- 开头但 fm 为空且 body 等于原始内容，说明解析失败。
            if content.startswith("---") and not fm and body == content:
                logger.error("Skill 文件夹 '%s' 的 SKILL.md YAML frontmatter 格式无效，跳过", folder.name)
                continue

            # 构建 SkillInfo
            folder_name = folder.name
            folder_path = str(folder.resolve())

            name = fm.get("name", folder_name)
            description = fm.get("description", "") or _extract_first_paragraph(body)
            when_to_use = fm.get("when_to_use", "")
            memory_categories = fm.get("memory_categories", []) or []
            allowed_tools = fm.get("allowed-tools", []) or []
            paths_val = fm.get("paths")
            is_conditional = paths_val is not None
            paths = list(paths_val) if paths_val else None

            # 验证 allowed-tools
            if self._registry and allowed_tools:
                for tool_name in allowed_tools:
                    if not self._registry.has_tool(tool_name):
                        logger.warning(
                            "Skill '%s' 引用了未注册的 Tool '%s'",
                            name, tool_name,
                        )

            # 检查正文是否包含"场景描述"段落
            if "场景描述" not in body:
                logger.warning("Skill '%s' 的正文缺少「场景描述」段落", name)

            skill = SkillInfo(
                name=name,
                description=description,
                when_to_use=when_to_use,
                memory_categories=memory_categories,
                allowed_tools=allowed_tools,
                folder_name=folder_name,
                folder_path=folder_path,
                body=body,
                is_conditional=is_conditional,
                paths=paths,
            )
            skills.append(skill)

        self._skills = skills
        return skills

    def to_prompt_section(self, activated_skills: set[str] | None = None) -> str:
        """生成 System Prompt 注入段落。

        - Unconditional Skill 始终列出完整摘要
        - 已激活的 Conditional Skill 列出完整摘要
        - 未激活的 Conditional Skill 仅列出名称和激活条件
        - 包含使用指引文本
        """
        if not self._skills:
            self.load_all()
        if not self._skills:
            return ""

        activated = activated_skills or set()

        lines = [
            "## 可用 Skills（场景参考规范）\n",
            "Skills 是场景参考规范，为你提供特定场景下的充足上下文、工具使用示例和典型流程参考。",
            "当你识别到用户进入某个场景时，调用 `get_skill_content(skill_name=\"...\")` 获取完整内容作为决策参考。",
            "Skill 内容仅作为参考信息，你应基于用户实际需求自主决策。\n",
        ]

        for skill in self._skills:
            if not skill.is_conditional or skill.name in activated:
                # 完整摘要
                lines.append(f"### {skill.name}")
                if skill.description:
                    lines.append(skill.description)
                if skill.when_to_use:
                    lines.append(f"适用场景: {skill.when_to_use}")
                if skill.allowed_tools:
                    lines.append(f"相关工具: {', '.join(skill.allowed_tools)}")
                lines.append("")
            else:
                # 未激活的 Conditional Skill：仅名称和激活条件
                paths_str = ", ".join(skill.paths) if skill.paths else ""
                lines.append(f"### {skill.name} [条件激活: 未激活]")
                lines.append(f"激活条件: paths 匹配 {paths_str}")
                lines.append("")

        return "\n".join(lines)

    def get_skill_content(self, skill_name: str) -> dict | None:
        """按需加载 Skill 完整内容。

        - 匹配 name 字段或 folder_name
        - 执行 ${SKILL_DIR} 变量替换（替换为文件夹绝对路径）
        - 返回 {content, allowed_tools, name, description} 或 None
        """
        if not self._skills:
            self.load_all()

        for skill in self._skills:
            if skill.name == skill_name or skill.folder_name == skill_name:
                content = skill.body.replace("${SKILL_DIR}", skill.folder_path)
                return {
                    "content": content,
                    "allowed_tools": skill.allowed_tools,
                    "name": skill.name,
                    "description": skill.description,
                }
        return None

    def get_all_skill_names(self) -> list[str]:
        """返回所有 Skill 名称列表，用于错误提示。"""
        if not self._skills:
            self.load_all()
        return [s.name for s in self._skills]
