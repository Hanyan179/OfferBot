"""
QueryJobsTool — 查询本地岗位数据

返回值分流：
  for_ui:    完整列表 → 前端渲染 JobList 卡片
  for_agent: 摘要 + id_map → AI 只看摘要，能定位具体岗位
"""

from __future__ import annotations

from collections import Counter
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
            "查询本地岗位数据。结果会直接渲染为列表展示给用户，你只会收到摘要信息。"
            "摘要包含匹配数量、薪资/城市分布、以及序号→岗位简称的 id_map。"
            "用户提到具体岗位时（如'第3个'、'字节那个'），通过 id_map 定位到岗位 id。"
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
                "search": {"type": "string", "description": "语义搜索（拆词后 OR 匹配 title 和 JD，适合自然语言描述）"},
                "city": {"type": "string", "description": "城市（模糊匹配）"},
                "company": {"type": "string", "description": "公司名称（模糊匹配）"},
                "salary_min": {"type": "integer", "description": "薪资下限（K/月）"},
                "salary_max": {"type": "integer", "description": "薪资上限（K/月）"},
                "education": {"type": "string", "description": "学历要求（如 本科、硕士）"},
                "experience": {"type": "string", "description": "经验要求（如 3-5年）"},
                "company_industry": {"type": "string", "description": "公司行业（如 互联网）"},
                "jd_status": {
                    "type": "string",
                    "enum": ["has_jd", "missing_jd", "stats"],
                    "description": "JD 状态过滤：has_jd=仅有JD的, missing_jd=缺JD的, stats=返回覆盖率统计",
                },
                "limit": {"type": "integer", "description": "返回数量上限", "default": 200},
            },
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db: Database = context["db"]

        # jd_status="stats" 快速返回覆盖率统计（这个 AI 需要看）
        if params.get("jd_status") == "stats":
            rows = await db.execute(
                "SELECT COUNT(*) as total,"
                " SUM(CASE WHEN raw_jd IS NOT NULL AND raw_jd != '' THEN 1 ELSE 0 END) as has_jd,"
                " SUM(CASE WHEN raw_jd IS NULL OR raw_jd = '' THEN 1 ELSE 0 END) as missing_jd"
                " FROM jobs"
            )
            return {"success": True, "jd_coverage": rows[0]}

        # ---- 构建 SQL ----
        clauses: list[str] = []
        values: list[Any] = []
        order_by = "discovered_at DESC"

        search_text = params.get("search")
        if search_text:
            words = [w for w in search_text.split() if len(w) >= 2]
            if words:
                or_parts = []
                for w in words:
                    or_parts.append("(title LIKE ? OR raw_jd LIKE ?)")
                    values.extend([f"%{w}%", f"%{w}%"])
                clauses.append(f"({' OR '.join(or_parts)})")
                score_expr = " + ".join(
                    f"(CASE WHEN title LIKE '%{w}%' THEN 2 ELSE 0 END + CASE WHEN raw_jd LIKE '%{w}%' THEN 1 ELSE 0 END)"
                    for w in words
                )
                order_by = f"({score_expr}) DESC"

        if kw := params.get("keyword"):
            for w in kw.split():
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

        jd_status = params.get("jd_status")
        if jd_status == "has_jd":
            clauses.append("raw_jd IS NOT NULL AND raw_jd != ''")
        elif jd_status == "missing_jd":
            clauses.append("(raw_jd IS NULL OR raw_jd = '')")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        limit = min(params.get("limit", 200), 500)

        # 先查总匹配数
        count_sql = f"SELECT COUNT(*) as cnt FROM jobs{where}"
        count_rows = await db.execute(count_sql, tuple(values))
        total_matched = count_rows[0]["cnt"] if count_rows else 0

        if total_matched == 0:
            total_rows = await db.execute("SELECT COUNT(*) as cnt FROM jobs")
            total = total_rows[0]["cnt"] if total_rows else 0
            if total == 0:
                return {
                    "success": True,
                    "for_agent": {
                        "count": 0,
                        "hint": "本地数据库暂无岗位数据。需要先通过猎聘获取岗位。",
                    },
                }
            return {
                "success": True,
                "for_agent": {
                    "count": 0,
                    "total_in_db": total,
                    "hint": f"本地共有 {total} 条岗位，但当前条件无匹配。建议放宽条件。",
                },
            }

        # 查数据
        sql = (
            f"SELECT id, title, company, salary_min, salary_max, city, url,"
            f" CASE WHEN raw_jd IS NOT NULL AND raw_jd != '' THEN 1 ELSE 0 END as has_jd,"
            f" CASE WHEN match_detail IS NOT NULL AND match_detail != '' THEN 1 ELSE 0 END as has_analysis,"
            f" CASE WHEN structured_jd IS NOT NULL AND structured_jd != '' THEN 1 ELSE 0 END as has_rag"
            f" FROM jobs{where} ORDER BY {order_by} LIMIT ?"
        )
        values_with_limit = list(values) + [limit]
        rows = await db.execute(sql, tuple(values_with_limit))

        # ---- 构建 for_ui ----
        ui_jobs = []
        for i, r in enumerate(rows):
            s_min = r.get("salary_min", 0) or 0
            s_max = r.get("salary_max", 0) or 0
            salary = f"{s_min}-{s_max}K" if s_min > 0 else "面议"
            ui_jobs.append({
                "seq": i + 1,
                "id": r["id"],
                "title": r["title"],
                "company": r["company"],
                "salary": salary,
                "city": r.get("city", ""),
                "url": r.get("url", ""),
                "has_jd": bool(r.get("has_jd")),
                "has_analysis": bool(r.get("has_analysis")),
                "has_rag": bool(r.get("has_rag")),
            })

        # ---- 构建 for_agent（极简摘要，不含具体岗位信息）----
        # AI 不需要看岗位列表，只需要知道查到了多少、大致分布
        # 用户提到具体岗位时，AI 通过序号从 session 中的 id_map 定位
        cities = Counter(j["city"].split("-")[0] for j in ui_jobs if j["city"])
        top_cities = ", ".join(f"{c}({n})" for c, n in cities.most_common(3))
        salaries = [j for j in ui_jobs if j["salary"] != "面议"]
        if salaries:
            s_vals = sorted(set(j["salary"] for j in salaries))
            salary_summary = f"薪资范围 {s_vals[0]}~{s_vals[-1]}" if len(s_vals) > 1 else f"薪资 {s_vals[0]}"
        else:
            salary_summary = "薪资未知"

        return {
            "success": True,
            "for_ui": {
                "element_name": "JobList",
                "jobs": ui_jobs,
                "total_matched": total_matched,
                "showing": len(ui_jobs),
            },
            "for_agent": {
                "displayed": len(ui_jobs),
                "total_matched": total_matched,
                "summary": f"已在 UI 展示 {len(ui_jobs)} 条岗位（共匹配 {total_matched} 条）。{top_cities}。",
                "note": "岗位列表已展示给用户，无需复述。用户提到具体岗位时再响应。",
            },
        }
