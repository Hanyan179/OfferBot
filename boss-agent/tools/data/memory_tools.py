"""
记忆工具集 — 基于 Markdown 文件的用户记忆系统

参考 Claude Code memdir 架构，每个分类一个独立 .md 文件，
AI 通过 Memory Tools 读写文件，实现用户认知模型的持久化。

包含工具：
- save_memory: 保存记忆条目
- get_memory: 读取指定分类记忆
- search_memory: 按关键词搜索所有记忆
- update_memory: 更新指定条目
- delete_memory: 删除指定条目
- list_memory_categories: 列出所有分类及条目数
- get_user_cognitive_model: 获取完整用户画像摘要
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.tool_registry import Tool

MEMORY_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "记忆画像")

# 预定义分类 → 文件名映射
CATEGORY_FILE_MAP: dict[str, str] = {
    "personal_thoughts": "个人想法.md",
    "job_sprint_goals": "求职冲刺目标.md",
    "language_style": "语言风格.md",
    "personality_traits": "性格特征.md",
    "hobbies_interests": "兴趣爱好.md",
    "career_planning": "职业规划.md",
    "personal_needs": "个人需求.md",
    "key_points": "要点信息.md",
    "communication_preferences": "沟通偏好.md",
    "values_beliefs": "价值观.md",
}

# 分类 → 中文名映射（用于文件一级标题）
CATEGORY_DISPLAY_NAME: dict[str, str] = {
    "personal_thoughts": "个人想法",
    "job_sprint_goals": "求职冲刺目标",
    "language_style": "语言风格",
    "personality_traits": "性格特征",
    "hobbies_interests": "兴趣爱好",
    "career_planning": "职业规划",
    "personal_needs": "个人需求",
    "key_points": "要点信息",
    "communication_preferences": "沟通偏好",
    "values_beliefs": "价值观",
}


def _get_memory_dir(context: Any = None) -> Path:
    """获取记忆画像文件夹路径，支持通过 context 覆盖（测试用）。"""
    if isinstance(context, dict) and "memory_dir" in context:
        return Path(context["memory_dir"])
    return Path(MEMORY_DIR)


def _get_file_path(category: str, memory_dir: Path) -> Path:
    """根据分类获取对应的 .md 文件路径。自定义分类自动生成文件名。"""
    filename = CATEGORY_FILE_MAP.get(category, f"{category}.md")
    return memory_dir / filename


def _get_display_name(category: str) -> str:
    """获取分类的中文显示名。自定义分类直接用分类名。"""
    return CATEGORY_DISPLAY_NAME.get(category, category)


def _ensure_dir(memory_dir: Path) -> None:
    """确保记忆画像文件夹存在。"""
    memory_dir.mkdir(parents=True, exist_ok=True)


def _parse_sections(content: str) -> list[dict]:
    """
    解析 Markdown 文件内容，按 ## 标题分割为段落列表。

    返回: [{"title": "标题", "body": "正文（含溯源行）", "raw": "完整原始文本（含 ## 行）"}, ...]
    """
    sections: list[dict] = []
    lines = content.split("\n")
    current_title: str | None = None
    current_lines: list[str] = []
    current_raw_lines: list[str] = []

    for line in lines:
        if line.startswith("## "):
            # 保存上一个段落
            if current_title is not None:
                sections.append({
                    "title": current_title,
                    "body": "\n".join(current_lines).strip(),
                    "raw": "\n".join(current_raw_lines),
                })
            current_title = line[3:].strip()
            current_lines = []
            current_raw_lines = [line]
        elif current_title is not None:
            current_lines.append(line)
            current_raw_lines.append(line)

    # 最后一个段落
    if current_title is not None:
        sections.append({
            "title": current_title,
            "body": "\n".join(current_lines).strip(),
            "raw": "\n".join(current_raw_lines),
        })

    return sections


class SaveMemoryTool(Tool):
    """保存记忆条目到对应分类的 Markdown 文件。"""

    @property
    def name(self) -> str:
        return "save_memory"

    @property
    def description(self) -> str:
        return "保存一条用户记忆。在对话中发现用户的想法、目标、性格、兴趣等信息时调用。"

    @property
    def category(self) -> str:
        return "memory"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "记忆分类（如 personal_thoughts, job_sprint_goals 等）",
                },
                "title": {
                    "type": "string",
                    "description": "记忆标题（简短概括）",
                },
                "content": {
                    "type": "string",
                    "description": "记忆内容（详细描述）",
                },
                "source_conversation_id": {
                    "type": "string",
                    "description": "来源会话 ID（用于溯源）",
                },
            },
            "required": ["category", "title", "content"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        category = params["category"]
        title = params["title"]
        content = params["content"]
        source_id = params.get("source_conversation_id", "unknown")

        memory_dir = _get_memory_dir(context)
        _ensure_dir(memory_dir)
        file_path = _get_file_path(category, memory_dir)

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 构建新条目
        entry = f"\n## {title}\n{content}\n\n> 来源: {source_id} | 提取于: {now}\n"

        if file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            file_path.write_text(existing.rstrip("\n") + "\n" + entry, encoding="utf-8")
        else:
            # 新文件：写入一级标题 + 条目
            display_name = _get_display_name(category)
            file_path.write_text(f"# {display_name}\n{entry}", encoding="utf-8")

        return {"saved": True, "category": category, "title": title}


class GetMemoryTool(Tool):
    """读取指定分类的记忆文件内容。"""

    @property
    def name(self) -> str:
        return "get_memory"

    @property
    def description(self) -> str:
        return "读取指定分类的所有记忆内容。"

    @property
    def category(self) -> str:
        return "memory"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "记忆分类名称",
                },
            },
            "required": ["category"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        category = params["category"]
        memory_dir = _get_memory_dir(context)
        file_path = _get_file_path(category, memory_dir)

        if not file_path.exists():
            return {"category": category, "content": "", "entries": 0}

        content = file_path.read_text(encoding="utf-8")
        sections = _parse_sections(content)
        return {"category": category, "content": content, "entries": len(sections)}


class SearchMemoryTool(Tool):
    """按关键词搜索所有记忆文件。"""

    @property
    def name(self) -> str:
        return "search_memory"

    @property
    def description(self) -> str:
        return "在所有记忆分类中按关键词搜索，返回匹配的内容片段。"

    @property
    def category(self) -> str:
        return "memory"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词",
                },
            },
            "required": ["keyword"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        keyword = params["keyword"].lower()
        memory_dir = _get_memory_dir(context)

        if not memory_dir.exists():
            return {"keyword": params["keyword"], "results": []}

        results: list[dict] = []
        for md_file in sorted(memory_dir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            # 反查分类名
            category = _filename_to_category(md_file.name)
            sections = _parse_sections(content)
            for section in sections:
                # 在标题和正文中搜索关键词（不区分大小写）
                if keyword in section["title"].lower() or keyword in section["body"].lower():
                    results.append({
                        "category": category,
                        "title": section["title"],
                        "content": section["body"],
                    })

        return {"keyword": params["keyword"], "results": results}


def _filename_to_category(filename: str) -> str:
    """从文件名反查分类英文名。找不到则返回文件名（去掉 .md）。"""
    for cat, fname in CATEGORY_FILE_MAP.items():
        if fname == filename:
            return cat
    return filename.removesuffix(".md")


class UpdateMemoryTool(Tool):
    """更新记忆文件中的指定条目。"""

    @property
    def name(self) -> str:
        return "update_memory"

    @property
    def description(self) -> str:
        return "更新指定分类中某个记忆条目的内容。通过标题定位条目。"

    @property
    def category(self) -> str:
        return "memory"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "记忆分类",
                },
                "title": {
                    "type": "string",
                    "description": "要更新的条目标题",
                },
                "new_content": {
                    "type": "string",
                    "description": "新的内容",
                },
            },
            "required": ["category", "title", "new_content"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        category = params["category"]
        title = params["title"]
        new_content = params["new_content"]

        memory_dir = _get_memory_dir(context)
        file_path = _get_file_path(category, memory_dir)

        if not file_path.exists():
            return {"updated": False, "error": f"分类 '{category}' 文件不存在"}

        content = file_path.read_text(encoding="utf-8")
        sections = _parse_sections(content)

        found = False
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for section in sections:
            if section["title"] == title:
                new_raw = f"## {title}\n{new_content}\n\n> 更新于: {now}"
                content = content.replace(section["raw"], new_raw)
                found = True
                break

        if not found:
            return {"updated": False, "error": f"未找到标题为 '{title}' 的条目"}

        file_path.write_text(content, encoding="utf-8")
        return {"updated": True, "category": category, "title": title}


class DeleteMemoryTool(Tool):
    """删除记忆文件中的指定条目。"""

    @property
    def name(self) -> str:
        return "delete_memory"

    @property
    def description(self) -> str:
        return "删除指定分类中某个记忆条目。通过标题定位条目。"

    @property
    def category(self) -> str:
        return "memory"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "记忆分类",
                },
                "title": {
                    "type": "string",
                    "description": "要删除的条目标题",
                },
            },
            "required": ["category", "title"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        category = params["category"]
        title = params["title"]

        memory_dir = _get_memory_dir(context)
        file_path = _get_file_path(category, memory_dir)

        if not file_path.exists():
            return {"deleted": False, "error": f"分类 '{category}' 文件不存在"}

        content = file_path.read_text(encoding="utf-8")
        sections = _parse_sections(content)

        found = False
        for section in sections:
            if section["title"] == title:
                # 移除该段落（包括前后可能的空行）
                content = content.replace(section["raw"], "")
                # 清理多余空行（连续3个以上换行合并为2个）
                while "\n\n\n" in content:
                    content = content.replace("\n\n\n", "\n\n")
                found = True
                break

        if not found:
            return {"deleted": False, "error": f"未找到标题为 '{title}' 的条目"}

        file_path.write_text(content, encoding="utf-8")
        return {"deleted": True, "category": category, "title": title}


class ListMemoryCategoryTool(Tool):
    """列出所有记忆分类及条目数量。"""

    @property
    def name(self) -> str:
        return "list_memory_categories"

    @property
    def description(self) -> str:
        return "返回所有记忆分类及每个分类下的条目数量。"

    @property
    def category(self) -> str:
        return "memory"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, params: dict, context: Any) -> dict:
        memory_dir = _get_memory_dir(context)

        if not memory_dir.exists():
            return {"categories": []}

        categories: list[dict] = []
        for md_file in sorted(memory_dir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            sections = _parse_sections(content)
            cat_name = _filename_to_category(md_file.name)
            categories.append({
                "category": cat_name,
                "file": md_file.name,
                "entries": len(sections),
            })

        return {"categories": categories}


class GetUserCognitiveModelTool(Tool):
    """获取用户认知模型完整摘要。"""

    @property
    def name(self) -> str:
        return "get_user_cognitive_model"

    @property
    def description(self) -> str:
        return "返回用户认知模型的完整摘要，读取所有记忆分类文件的内容。"

    @property
    def category(self) -> str:
        return "memory"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, params: dict, context: Any) -> dict:
        memory_dir = _get_memory_dir(context)

        if not memory_dir.exists():
            return {"summary": "", "categories_included": []}

        parts: list[str] = []
        included: list[str] = []

        for md_file in sorted(memory_dir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8").strip()
            # 只包含有实际条目的文件（有 ## 标题的）
            sections = _parse_sections(content)
            if sections:
                cat_name = _filename_to_category(md_file.name)
                parts.append(content)
                included.append(cat_name)

        return {
            "summary": "\n\n---\n\n".join(parts),
            "categories_included": included,
        }
