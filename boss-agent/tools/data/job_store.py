"""
岗位数据 CRUD 工具

SaveJobTool: 保存岗位数据到数据库（以 URL 去重）
辅助函数: query_jobs, update_match_score, update_structured_jd, get_job_by_url, get_job_by_id
"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool
from db.database import Database


class SaveJobTool(Tool):
    """保存岗位数据到数据库，以 URL 为唯一标识去重。"""

    @property
    def name(self) -> str:
        return "save_job"

    @property
    def display_name(self) -> str:
        return "保存岗位"

    @property
    def description(self) -> str:
        return "保存岗位数据到数据库（去重）"

    @property
    def category(self) -> str:
        return "data"

    @property
    def is_concurrency_safe(self) -> bool:
        return False

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "岗位 URL（唯一标识）"},
                "platform": {"type": "string", "description": "招聘平台", "default": "boss"},
                "title": {"type": "string", "description": "岗位名称"},
                "company": {"type": "string", "description": "公司名称"},
                "salary_min": {"type": "integer", "description": "薪资下限（K/月）"},
                "salary_max": {"type": "integer", "description": "薪资上限（K/月）"},
                "salary_months": {"type": "integer", "description": "薪资月数（如13薪）"},
                "city": {"type": "string", "description": "工作城市"},
                "district": {"type": "string", "description": "区/商圈"},
                "work_type": {"type": "string", "description": "工作类型: full_time/part_time/remote/hybrid"},
                "experience": {"type": "string", "description": "经验要求原文"},
                "experience_min": {"type": "integer", "description": "经验要求下限（年）"},
                "experience_max": {"type": "integer", "description": "经验要求上限（年）"},
                "education": {"type": "string", "description": "学历要求"},
                "skills": {"type": "string", "description": "技能要求 JSON 数组"},
                "skills_must": {"type": "string", "description": "必须技能 JSON 数组"},
                "skills_preferred": {"type": "string", "description": "优先技能 JSON 数组"},
                "responsibilities": {"type": "string", "description": "岗位职责 JSON 数组"},
                "company_size": {"type": "string", "description": "公司规模"},
                "company_industry": {"type": "string", "description": "公司行业"},
                "company_stage": {"type": "string", "description": "公司阶段"},
                "company_description": {"type": "string", "description": "公司简介"},
                "recruiter_name": {"type": "string", "description": "招聘者姓名"},
                "recruiter_title": {"type": "string", "description": "招聘者职位"},
                "benefits": {"type": "string", "description": "福利待遇 JSON 数组"},
                "tags": {"type": "string", "description": "岗位标签 JSON 数组"},
                "raw_jd": {"type": "string", "description": "原始 JD 文本"},
            },
            "required": ["url"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        """插入岗位数据，URL 重复时静默忽略。返回 {"job_id": int | None}。"""
        db: Database = context["db"]

        columns = [
            "url", "platform", "title", "company",
            "salary_min", "salary_max", "salary_months",
            "city", "district", "work_type",
            "experience", "experience_min", "experience_max",
            "education", "skills", "skills_must", "skills_preferred",
            "responsibilities",
            "company_size", "company_industry", "company_stage", "company_description",
            "recruiter_name", "recruiter_title",
            "benefits", "tags", "raw_jd",
        ]

        present_cols: list[str] = []
        values: list[Any] = []
        for col in columns:
            if col in params:
                present_cols.append(col)
                values.append(params[col])

        placeholders = ", ".join("?" for _ in present_cols)
        col_names = ", ".join(present_cols)

        sql = f"INSERT OR IGNORE INTO jobs ({col_names}) VALUES ({placeholders})"

        # Use raw connection to check rowcount for duplicate detection
        assert db._conn is not None, "Database not connected."
        cursor = await db._conn.execute(sql, tuple(values))
        await db._conn.commit()

        if cursor.rowcount == 0:
            # Row already exists — look up existing id
            existing = await get_job_by_url(db, params["url"])
            return {"job_id": existing["id"] if existing else None, "inserted": False}

        return {"job_id": cursor.lastrowid, "inserted": True}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def query_jobs(
    db: Database,
    filters: dict | None = None,
) -> list[dict]:
    """按条件查询岗位列表。

    支持的 filters 键:
        city: 精确匹配城市
        company: 精确匹配公司
        min_match_score: 匹配度 >= 该值
        keyword: 标题模糊搜索 (LIKE %keyword%)
    """
    clauses: list[str] = []
    params: list[Any] = []

    if filters:
        if "city" in filters:
            clauses.append("city = ?")
            params.append(filters["city"])
        if "company" in filters:
            clauses.append("company = ?")
            params.append(filters["company"])
        if "min_match_score" in filters:
            clauses.append("match_score >= ?")
            params.append(filters["min_match_score"])
        if "keyword" in filters:
            clauses.append("title LIKE ?")
            params.append(f"%{filters['keyword']}%")

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM jobs{where} ORDER BY id"
    return await db.execute(sql, tuple(params))


async def update_match_score(
    db: Database,
    job_id: int,
    score: float,
    detail: str,
) -> None:
    """更新岗位的匹配度和匹配详情。"""
    await db.execute_write(
        "UPDATE jobs SET match_score = ?, match_detail = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (score, detail, job_id),
    )


async def update_structured_jd(
    db: Database,
    job_id: int,
    structured_jd: str,
) -> None:
    """更新岗位的结构化 JD 并设置 parsed_at。"""
    await db.execute_write(
        "UPDATE jobs SET structured_jd = ?, parsed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (structured_jd, job_id),
    )


async def get_job_by_url(db: Database, url: str) -> dict | None:
    """根据 URL 获取单条岗位记录。"""
    rows = await db.execute("SELECT * FROM jobs WHERE url = ?", (url,))
    return rows[0] if rows else None


async def get_job_by_id(db: Database, job_id: int) -> dict | None:
    """根据 ID 获取单条岗位记录。"""
    rows = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    return rows[0] if rows else None
