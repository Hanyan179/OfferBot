"""
QueryJobsTool — 查询本地岗位数据

让 AI 能从 jobs 表中按条件检索岗位，用于数据分析、匹配推荐等场景。
"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool
from db.database import Database


class QueryJobsTool(Tool):
    """查询本地数据库中的岗位数据，支持多条件筛选。"""

    @property
    def name(self) -> str:
        return "query_jobs"

    @property
    def display_name(self) -> str:
        return "搜索岗位"

    @property
    def description(self) -> str:
        return (
            "查询本地数据库中已爬取的岗位数据。"
            "支持按城市、公司、关键词、薪资范围等条件筛选。"
            "返回岗位列表（含标题、公司、薪资、JD、链接等）。"
        )

    @property
    def category(self) -> str:
        return "data"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "岗位名称关键词（模糊搜索）"},
                "city": {"type": "string", "description": "城市（精确匹配）"},
                "company": {"type": "string", "description": "公司名称（精确匹配）"},
                "salary_min": {"type": "integer", "description": "薪资下限（K/月），筛选 salary_min >= 此值的岗位"},
                "salary_max": {"type": "integer", "description": "薪资上限（K/月），筛选 salary_min <= 此值的岗位"},
                "education": {"type": "string", "description": "学历要求（精确匹配，如 本科、硕士）"},
                "experience": {"type": "string", "description": "经验要求（模糊匹配，如 3-5年）"},
                "company_industry": {"type": "string", "description": "公司行业（模糊匹配，如 互联网）"},
                "limit": {"type": "integer", "description": "返回数量上限", "default": 20},
            },
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db: Database = context["db"]

        clauses: list[str] = []
        values: list[Any] = []

        if kw := params.get("keyword"):
            clauses.append("title LIKE ?")
            values.append(f"%{kw}%")
        if city := params.get("city"):
            clauses.append("city LIKE ?")
            values.append(f"%{city}%")
        if company := params.get("company"):
            clauses.append("company LIKE ?")
            values.append(f"%{company}%")
        if s_min := params.get("salary_min"):
            clauses.append("salary_min >= ?")
            values.append(s_min)
        if s_max := params.get("salary_max"):
            clauses.append("salary_min <= ?")
            values.append(s_max)
        if edu := params.get("education"):
            clauses.append("education = ?")
            values.append(edu)
        if exp := params.get("experience"):
            clauses.append("experience LIKE ?")
            values.append(f"%{exp}%")
        if industry := params.get("company_industry"):
            clauses.append("company_industry LIKE ?")
            values.append(f"%{industry}%")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        limit = min(params.get("limit", 20), 50)

        sql = f"SELECT id, url, title, company, salary_min, salary_max, salary_months, city, experience, education, match_score FROM jobs{where} ORDER BY discovered_at DESC LIMIT ?"
        values.append(limit)

        rows = await db.execute(sql, tuple(values))
        return {
            "success": True,
            "count": len(rows),
            "jobs": rows,
        }
