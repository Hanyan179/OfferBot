"""
Context Builder — 构建上下文前言，避免 LLM 重复调用工具获取已有信息

在每轮对话发给 LLM 之前，把已加载的用户档案、记忆画像等信息
拼接为一段"上下文快照"，附在 system prompt 末尾。
LLM 看到数据已经在眼前，就不会再调工具去重复获取。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from db.database import Database
from tools.data.memory_tools import GetUserCognitiveModelTool

logger = logging.getLogger(__name__)


class ContextBuilder:
    """构建 context preamble，让 LLM 知道哪些信息已经加载、无需重复获取。"""

    def __init__(self) -> None:
        self._profile_cache: dict | None = None
        self._memory_cache: str = ""

    async def build_preamble(self, db: Database | None = None) -> str:
        """
        构建完整的上下文前言文本。

        在 on_chat_start 时调用一次，结果缓存在 session 中。
        后续每轮对话直接使用缓存，不重复查询。

        Returns:
            拼接好的 context preamble 字符串，可直接附在 system prompt 后面。
        """
        sections: list[str] = []

        # 1. 用户档案
        profile_section = await self._build_profile_section(db)
        if profile_section:
            sections.append(profile_section)

        # 2. 记忆画像摘要
        memory_section = await self._build_memory_section()
        if memory_section:
            sections.append(memory_section)

        if not sections:
            return ""

        header = (
            "\n\n## 当前已加载的上下文\n\n"
            "以下信息已在对话开始时加载，你可以直接使用，无需调用工具重复获取。\n"
            "只有当你需要**更新**数据（如用户提供了新信息）时，才调用对应的写入工具。\n"
        )
        return header + "\n\n".join(sections)

    async def _build_profile_section(self, db: Database | None) -> str:
        """构建用户档案段落。"""
        if db is None:
            return ""

        try:
            rows = await db.execute(
                "SELECT * FROM resumes WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
            )
        except Exception as e:
            logger.warning("加载用户档案失败: %s", e)
            return ""

        if not rows or not rows[0].get("name"):
            return "### 用户档案\n\n用户尚未建立个人档案。（无需调用 get_user_profile，确认没有档案）"

        r = rows[0]
        self._profile_cache = r

        # 构建可读摘要
        lines = ["### 用户档案（已加载，无需调用 get_user_profile）\n"]

        # 基本信息
        basics = []
        if r.get("name"):
            basics.append(f"姓名: {r['name']}")
        if r.get("city"):
            basics.append(f"城市: {r['city']}")
        if r.get("current_role"):
            basics.append(f"当前职位: {r['current_role']}")
        if r.get("current_company"):
            basics.append(f"当前公司: {r['current_company']}")
        if r.get("years_of_experience"):
            basics.append(f"工作年限: {r['years_of_experience']}年")
        if r.get("education_level"):
            edu = r["education_level"]
            if r.get("school"):
                edu += f" · {r['school']}"
            if r.get("education_major"):
                edu += f" · {r['education_major']}"
            basics.append(f"学历: {edu}")
        if basics:
            lines.append(" | ".join(basics))

        # 技能
        skills = _safe_json(r.get("skills_flat"))
        if skills and isinstance(skills, list):
            lines.append(f"技能: {', '.join(skills[:15])}")

        # 简介
        if r.get("summary"):
            lines.append(f"简介: {r['summary'][:200]}")

        # 求职意向（如果有）
        try:
            pref_rows = await db.execute(
                "SELECT * FROM job_preferences WHERE resume_id = ? AND is_active = 1 LIMIT 1",
                (r["id"],),
            )
            if pref_rows:
                pref = pref_rows[0]
                pref_parts = []
                cities = _safe_json(pref.get("target_cities"))
                if cities:
                    pref_parts.append(f"目标城市: {', '.join(cities)}")
                roles = _safe_json(pref.get("target_roles"))
                if roles:
                    pref_parts.append(f"目标岗位: {', '.join(roles)}")
                if pref.get("salary_min") or pref.get("salary_max"):
                    sal = f"{pref.get('salary_min', '?')}K-{pref.get('salary_max', '?')}K"
                    pref_parts.append(f"期望薪资: {sal}")
                if pref_parts:
                    lines.append("求职意向: " + " | ".join(pref_parts))
        except Exception:
            pass

        return "\n".join(lines)

    async def _build_memory_section(self) -> str:
        """构建记忆画像摘要段落。"""
        try:
            result = await GetUserCognitiveModelTool().execute({}, {})
            summary = result.get("summary", "")
            self._memory_cache = summary
        except Exception as e:
            logger.warning("加载记忆画像失败: %s", e)
            return ""

        if not summary:
            return ""

        return (
            "### 记忆画像摘要（已加载，无需调用 get_user_cognitive_model）\n\n"
            f"{summary}\n\n"
            "需要某个分类的详细内容时，可调用 get_memory(category)。"
        )

    @property
    def has_profile(self) -> bool:
        return self._profile_cache is not None and bool(self._profile_cache.get("name"))

    @property
    def profile_name(self) -> str:
        return (self._profile_cache or {}).get("name", "")

    @property
    def profile_city(self) -> str:
        return (self._profile_cache or {}).get("city", "")

    @property
    def profile_role(self) -> str:
        return (self._profile_cache or {}).get("current_role", "")


def _safe_json(val: str | None) -> Any:
    if not val:
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return val
