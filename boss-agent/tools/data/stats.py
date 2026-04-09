"""
投递统计工具

GetStatsTool: 查询投递统计数据（总数、回复率、面试邀约率、按公司/岗位分布）
"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool
from db.database import Database


class GetStatsTool(Tool):
    """查询投递统计数据。"""

    @property
    def name(self) -> str:
        return "get_stats"

    @property
    def display_name(self) -> str:
        return "投递统计"

    @property
    def description(self) -> str:
        return "查询投递统计数据"

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
            "properties": {},
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db: Database = context["db"]

        # 投递总数
        rows = await db.execute("SELECT COUNT(*) AS cnt FROM applications")
        total_applications = rows[0]["cnt"]

        # 已回复数
        total_replied = 0

        reply_rate = total_replied / total_applications if total_applications else 0.0

        # 面试邀约数
        total_interviews = 0

        interview_rate = total_interviews / total_applications if total_applications else 0.0

        # 平均匹配度
        rows = await db.execute(
            "SELECT AVG(j.match_score) AS avg_score "
            "FROM applications a JOIN jobs j ON a.job_id = j.id "
            "WHERE j.match_score IS NOT NULL"
        )
        avg_match_score = rows[0]["avg_score"] if rows[0]["avg_score"] is not None else 0.0

        # 按公司分布
        by_company = await db.execute(
            "SELECT j.company AS company, COUNT(*) AS count "
            "FROM applications a JOIN jobs j ON a.job_id = j.id "
            "GROUP BY j.company ORDER BY count DESC"
        )

        # 按岗位名称分布
        by_title = await db.execute(
            "SELECT j.title AS title, COUNT(*) AS count "
            "FROM applications a JOIN jobs j ON a.job_id = j.id "
            "GROUP BY j.title ORDER BY count DESC"
        )

        stats = {
            "total_applications": total_applications,
            "total_replied": total_replied,
            "reply_rate": reply_rate,
            "total_interviews": total_interviews,
            "interview_rate": interview_rate,
            "avg_match_score": avg_match_score,
            "by_company": [dict(r) for r in by_company],
            "by_title": [dict(r) for r in by_title],
        }

        return {
            "for_ui": {
                "element_name": "BadgeWall",
                "cards": [
                    {"label": "总投递", "value": total_applications},
                    {"label": "已回复", "value": total_replied},
                    {"label": "回复率", "value": f"{reply_rate:.0%}"},
                    {"label": "面试邀约", "value": total_interviews},
                    {"label": "面试率", "value": f"{interview_rate:.0%}"},
                    {"label": "平均匹配度", "value": f"{avg_match_score:.1f}"},
                ],
                "stats": stats,
            },
            "for_agent": stats,
        }
