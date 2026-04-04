"""
Skills 加载器 — 加载 Markdown Skill 文件并生成 System Prompt 注入段落

参考 Claude Code 的 loadSkillsDir.ts 设计：
- 每个 Skill 是一个 Markdown 文件，带 YAML frontmatter
- frontmatter 包含 name、description、when_to_use、memory_categories、allowed-tools
- System Prompt 只注入摘要（name + description + when_to_use），节省 token
- 完整内容按需加载
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR = "boss-agent/skills"


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


class SkillLoader:
    """
    加载 skills/ 目录下的 Markdown Skill 文件。

    每个 Skill 文件的 frontmatter 包含：
    - name: Skill 名称
    - description: 简短描述
    - when_to_use: 何时使用
    - memory_categories: 需要读取的记忆分类列表
    - allowed-tools: 允许使用的工具列表
    """

    def __init__(self, skills_dir: str | None = None):
        self.skills_dir = Path(skills_dir or SKILLS_DIR)

    def load_all(self) -> list[dict[str, Any]]:
        """
        扫描 skills/ 目录，解析每个 .md 文件的 frontmatter。

        Returns:
            结构化的 Skill 列表，每项包含 frontmatter 字段 + file + body
        """
        if not self.skills_dir.exists():
            return []

        skills: list[dict[str, Any]] = []
        for md_file in sorted(self.skills_dir.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
                fm, body = _parse_frontmatter(content)

                skill = {
                    "name": fm.get("name", md_file.stem),
                    "description": fm.get("description", ""),
                    "when_to_use": fm.get("when_to_use", ""),
                    "memory_categories": fm.get("memory_categories", []),
                    "allowed_tools": fm.get("allowed-tools", []),
                    "file": md_file.name,
                    "body": body,
                }
                skills.append(skill)
            except Exception as e:
                logger.warning("跳过 Skill 文件 %s: %s", md_file.name, e)

        return skills

    def to_prompt_section(self) -> str:
        """
        生成 System Prompt 注入段落。

        只包含 name + description + when_to_use，节省 token。
        """
        skills = self.load_all()
        if not skills:
            return ""

        lines = ["## 可用 Skills\n"]
        for s in skills:
            lines.append(f"### {s['name']}")
            if s["description"]:
                lines.append(s["description"])
            if s["when_to_use"]:
                lines.append(f"适用场景: {s['when_to_use']}")
            lines.append("")

        return "\n".join(lines)

    def get_skill_content(self, skill_name: str) -> str | None:
        """
        按需加载单个 Skill 的完整 Markdown 内容（含 body）。

        Args:
            skill_name: Skill 名称（匹配 frontmatter 的 name 字段或文件名）

        Returns:
            完整的 Markdown 内容，找不到返回 None
        """
        if not self.skills_dir.exists():
            return None

        for md_file in self.skills_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                fm, body = _parse_frontmatter(content)
                name = fm.get("name", md_file.stem)
                if name == skill_name or md_file.stem == skill_name:
                    return content
            except Exception:
                continue

        return None
