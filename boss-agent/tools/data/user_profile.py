"""
用户档案工具 — 让 Agent 在对话中静默读写用户信息

包含两个工具：
- get_user_profile: 读取用户当前档案（简历 + 求职意向）
- update_user_profile: 更新用户档案的任意字段
"""

from __future__ import annotations

import json
from typing import Any

from agent.tool_registry import Tool
from db.database import Database


class GetUserProfileTool(Tool):
    """读取用户当前档案（简历信息 + 求职意向）。"""

    @property
    def name(self) -> str:
        return "get_user_profile"

    @property
    def display_name(self) -> str:
        return "获取用户档案"

    @property
    def description(self) -> str:
        return "获取用户的个人档案，包括基本信息、技能、工作经历、求职意向等。用于了解用户当前状态。"

    @property
    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "data"

    async def execute(self, params: dict, context: Any) -> dict:
        db: Database = context.get("db") if isinstance(context, dict) else None
        if db is None:
            return {"error": "数据库未连接"}

        # 读取当前活跃简历
        rows = await db.execute(
            "SELECT * FROM resumes WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        )
        resume = rows[0] if rows else None

        # 读取求职意向
        prefs = None
        if resume:
            pref_rows = await db.execute(
                "SELECT * FROM job_preferences WHERE resume_id = ? AND is_active = 1 LIMIT 1",
                (resume["id"],),
            )
            prefs = pref_rows[0] if pref_rows else None

        if resume is None:
            return {"has_profile": False, "message": "用户尚未建立个人档案"}

        # 构建可读的档案摘要
        profile = {
            "has_profile": True,
            "resume_id": resume["id"],
            "name": resume.get("name"),
            "phone": resume.get("phone"),
            "email": resume.get("email"),
            "city": resume.get("city"),
            "education_level": resume.get("education_level"),
            "school": resume.get("school"),
            "education_major": resume.get("education_major"),
            "years_of_experience": resume.get("years_of_experience"),
            "current_company": resume.get("current_company"),
            "current_role": resume.get("current_role"),
            "summary": resume.get("summary"),
            "self_evaluation": resume.get("self_evaluation"),
            "skills": _safe_json_load(resume.get("skills_flat")),
            "tech_stack": _safe_json_load(resume.get("tech_stack")),
            "work_experience": _safe_json_load(resume.get("work_experience")),
            "projects": _safe_json_load(resume.get("projects")),
            "highlights": _safe_json_load(resume.get("highlights")),
        }

        if prefs:
            profile["job_preferences"] = {
                "target_cities": _safe_json_load(prefs.get("target_cities")),
                "target_roles": _safe_json_load(prefs.get("target_roles")),
                "salary_min": prefs.get("salary_min"),
                "salary_max": prefs.get("salary_max"),
                "work_type": prefs.get("work_type"),
                "deal_breakers": _safe_json_load(prefs.get("deal_breakers")),
                "priorities": _safe_json_load(prefs.get("priorities")),
            }

        return profile


class UpdateUserProfileTool(Tool):
    """
    更新用户档案。Agent 在对话中捕捉到用户信息时调用此工具静默更新。

    支持更新的字段包括简历基本信息和求职意向。
    只需传入要更新的字段，未传入的字段保持不变。
    """

    @property
    def name(self) -> str:
        return "update_user_profile"

    @property
    def display_name(self) -> str:
        return "更新用户档案"

    @property
    def description(self) -> str:
        return (
            "更新用户个人档案。在对话中发现用户新信息时调用（如城市、技能、薪资期望等）。"
            "只需传入要更新的字段，其他字段保持不变。如果用户还没有档案会自动创建。"
            "当用户上传简历时，应一次性传入所有解析出的字段（包括 work_experience、projects、tech_stack 等），"
            "实现全量更新。work_experience 和 projects 是 JSON 数组，tech_stack 是 JSON 对象。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "姓名"},
                "phone": {"type": "string", "description": "手机号"},
                "email": {"type": "string", "description": "邮箱"},
                "birth_year": {"type": "integer", "description": "出生年份"},
                "city": {"type": "string", "description": "现居城市"},
                "education_level": {"type": "string", "description": "学历（大专/本科/硕士/博士）"},
                "school": {"type": "string", "description": "学校"},
                "education_major": {"type": "string", "description": "专业"},
                "years_of_experience": {"type": "integer", "description": "工作年限"},
                "current_company": {"type": "string", "description": "当前公司"},
                "current_role": {"type": "string", "description": "当前职位"},
                "summary": {"type": "string", "description": "个人简介/自我介绍"},
                "self_evaluation": {"type": "string", "description": "自我评价"},
                "skills": {"type": "array", "items": {"type": "string"}, "description": "扁平技能列表，如 ['Python', 'FastAPI', 'RAG']"},
                "tech_stack": {
                    "type": "object",
                    "description": "技术栈字典，按领域分组，如 {'AI': ['PyTorch', 'LangChain'], 'Web': ['FastAPI', 'React']}",
                },
                "work_experience": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "company": {"type": "string"},
                            "role": {"type": "string"},
                            "duration": {"type": "string"},
                            "tech_stack": {"type": "string"},
                            "description": {"type": "string"},
                            "highlights": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "description": "工作经历列表",
                },
                "projects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "tech_stack": {"type": "string"},
                            "highlights": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "description": "项目经验列表",
                },
                "highlights": {"type": "array", "items": {"type": "string"}, "description": "核心亮点"},
                "raw_text": {"type": "string", "description": "简历原始文本（上传简历时保存完整原文）"},
                "target_cities": {"type": "array", "items": {"type": "string"}, "description": "目标城市列表"},
                "target_roles": {"type": "array", "items": {"type": "string"}, "description": "目标岗位类型"},
                "target_industries": {"type": "array", "items": {"type": "string"}, "description": "目标行业"},
                "salary_min": {"type": "integer", "description": "期望薪资下限（K/月）"},
                "salary_max": {"type": "integer", "description": "期望薪资上限（K/月）"},
                "work_type": {"type": "string", "description": "工作类型: full_time/remote/hybrid"},
                "deal_breakers": {"type": "array", "items": {"type": "string"}, "description": "绝对不接受的条件"},
                "priorities": {"type": "array", "items": {"type": "string"}, "description": "求职优先级"},
            },
            "required": [],
        }

    @property
    def category(self) -> str:
        return "data"

    async def execute(self, params: dict, context: Any) -> dict:
        db: Database = context.get("db") if isinstance(context, dict) else None
        if db is None:
            return {"error": "数据库未连接"}

        # 获取或创建活跃简历
        rows = await db.execute(
            "SELECT id FROM resumes WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        )
        if rows:
            resume_id = rows[0]["id"]
        else:
            resume_id = await db.execute_write(
                "INSERT INTO resumes (is_active) VALUES (1)"
            )

        # 更新简历字段
        resume_fields = {
            "name", "phone", "email", "birth_year", "city",
            "education_level", "school", "education_major",
            "years_of_experience", "current_company", "current_role",
            "summary", "self_evaluation", "raw_text",
        }
        resume_updates = {}
        for field in resume_fields:
            if field in params and params[field] is not None:
                resume_updates[field] = params[field]

        # 处理 JSON 数组/对象字段
        if "skills" in params:
            resume_updates["skills_flat"] = json.dumps(params["skills"], ensure_ascii=False)
        if "tech_stack" in params:
            resume_updates["tech_stack"] = json.dumps(params["tech_stack"], ensure_ascii=False)
        if "work_experience" in params:
            resume_updates["work_experience"] = json.dumps(params["work_experience"], ensure_ascii=False)
        if "projects" in params:
            resume_updates["projects"] = json.dumps(params["projects"], ensure_ascii=False)
        if "highlights" in params:
            resume_updates["highlights"] = json.dumps(params["highlights"], ensure_ascii=False)

        if resume_updates:
            resume_updates["updated_at"] = "CURRENT_TIMESTAMP"
            set_clause = ", ".join(
                f"{k} = ?" if k != "updated_at" else f"{k} = CURRENT_TIMESTAMP"
                for k in resume_updates
            )
            values = [v for k, v in resume_updates.items() if k != "updated_at"]
            values.append(resume_id)
            await db.execute_write(
                f"UPDATE resumes SET {set_clause} WHERE id = ?",
                tuple(values),
            )

        # 更新求职意向
        pref_fields = {
            "target_cities", "target_roles", "target_industries",
            "salary_min", "salary_max",
            "work_type", "deal_breakers", "priorities",
        }
        pref_updates = {}
        for field in pref_fields:
            if field in params and params[field] is not None:
                val = params[field]
                if isinstance(val, (list, dict)):
                    val = json.dumps(val, ensure_ascii=False)
                pref_updates[field] = val

        if pref_updates:
            # 获取或创建求职意向
            pref_rows = await db.execute(
                "SELECT id FROM job_preferences WHERE resume_id = ? AND is_active = 1 LIMIT 1",
                (resume_id,),
            )
            if pref_rows:
                pref_id = pref_rows[0]["id"]
                set_clause = ", ".join(f"{k} = ?" for k in pref_updates)
                values = list(pref_updates.values()) + [pref_id]
                await db.execute_write(
                    f"UPDATE job_preferences SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    tuple(values),
                )
            else:
                pref_updates["resume_id"] = resume_id
                cols = ", ".join(pref_updates.keys())
                placeholders = ", ".join("?" for _ in pref_updates)
                await db.execute_write(
                    f"INSERT INTO job_preferences ({cols}) VALUES ({placeholders})",
                    tuple(pref_updates.values()),
                )

        updated_fields = list(resume_updates.keys()) + list(pref_updates.keys())
        updated_fields = [f for f in updated_fields if f != "updated_at"]
        return {"updated": True, "fields": updated_fields}


def _safe_json_load(val: str | None) -> Any:
    if not val:
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return val
