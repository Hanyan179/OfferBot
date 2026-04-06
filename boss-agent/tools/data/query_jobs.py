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
            "查询本地岗位数据，返回精简列表（id、标题、公司、薪资、城市、链接）。"
            "用于第一轮筛选和展示，不含 JD 详情。"
            "需要详情时用 fetch_job_detail 获取。"
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
                "keyword": {"type": "string", "description": "岗位名称关键词（拆词后 AND 匹配 title）"},
                "search": {"type": "string", "description": "语义搜索（拆词后 OR 匹配 title 和 JD，适合自然语言描述如'AI Agent 架构方向'）"},
                "city": {"type": "string", "description": "城市（模糊匹配）"},
                "company": {"type": "string", "description": "公司名称（模糊匹配）"},
                "salary_min": {"type": "integer", "description": "薪资下限（K/月），筛选 salary_min >= 此值的岗位"},
                "salary_max": {"type": "integer", "description": "薪资上限（K/月），筛选 salary_min <= 此值的岗位"},
                "education": {"type": "string", "description": "学历要求（精确匹配，如 本科、硕士）"},
                "experience": {"type": "string", "description": "经验要求（模糊匹配，如 3-5年）"},
                "company_industry": {"type": "string", "description": "公司行业（模糊匹配，如 互联网）"},
                "jd_status": {
                    "type": "string",
                    "enum": ["has_jd", "missing_jd", "stats"],
                    "description": "JD 状态过滤：has_jd=仅有JD的, missing_jd=缺JD的, stats=返回覆盖率统计",
                },
                "limit": {"type": "integer", "description": "返回数量上限", "default": 20},
            },
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db: Database = context["db"]

        # jd_status="stats" 快速返回覆盖率统计
        if params.get("jd_status") == "stats":
            rows = await db.execute(
                "SELECT COUNT(*) as total,"
                " SUM(CASE WHEN raw_jd IS NOT NULL AND raw_jd != '' THEN 1 ELSE 0 END) as has_jd,"
                " SUM(CASE WHEN raw_jd IS NULL OR raw_jd = '' THEN 1 ELSE 0 END) as missing_jd"
                " FROM jobs"
            )
            return {"success": True, "jd_coverage": rows[0]}

        clauses: list[str] = []
        values: list[Any] = []

        # search: 语义搜索，拆词 OR 匹配 title + raw_jd，按命中词数排序
        search_text = params.get("search")
        order_by = "discovered_at DESC"

        if search_text:
            words = [w for w in search_text.split() if len(w) >= 2]
            if words:
                or_parts = []
                for w in words:
                    or_parts.append("(title LIKE ? OR raw_jd LIKE ?)")
                    values.append(f"%{w}%")
                    values.append(f"%{w}%")
                clauses.append(f"({' OR '.join(or_parts)})")
                # 按命中词数排序：命中越多越靠前
                score_expr = " + ".join(
                    f"(CASE WHEN title LIKE '%{w}%' THEN 2 ELSE 0 END + CASE WHEN raw_jd LIKE '%{w}%' THEN 1 ELSE 0 END)"
                    for w in words
                )
                order_by = f"({score_expr}) DESC"

        if kw := params.get("keyword"):
            words = kw.split()
            for w in words:
                clauses.append("title LIKE ?")
                values.append(f"%{w}%")
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

        # jd_status 过滤
        jd_status = params.get("jd_status")
        if jd_status == "has_jd":
            clauses.append("raw_jd IS NOT NULL AND raw_jd != ''")
        elif jd_status == "missing_jd":
            clauses.append("(raw_jd IS NULL OR raw_jd = '')")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        limit = min(params.get("limit", 20), 50)

        sql = f"SELECT id, title, company, salary_min, salary_max, city, url FROM jobs{where} ORDER BY {order_by} LIMIT ?"
        values.append(limit)

        rows = await db.execute(sql, tuple(values))

        if not rows:
            # 查总量判断是库里完全没数据还是筛选条件没匹配
            total_rows = await db.execute("SELECT COUNT(*) as cnt FROM jobs")
            total = total_rows[0]["cnt"] if total_rows else 0
            if total == 0:
                return {
                    "success": True,
                    "count": 0,
                    "jobs": [],
                    "hint": "本地数据库暂无岗位数据。需要先通过猎聘爬取岗位：1) getjob_service_manage(action='check') 检查服务 2) platform_update_config 配置搜索条件 3) platform_start_task 启动爬取，爬取完成后系统自动同步到本地。",
                }
            return {
                "success": True,
                "count": 0,
                "jobs": [],
                "hint": f"本地共有 {total} 条岗位数据，但当前筛选条件无匹配结果。建议放宽条件重新查询。",
            }

        return {
            "success": True,
            "count": len(rows),
            "jobs": rows,
        }
