"""
CSV 导出工具

ExportCSVTool: 导出投递记录为 CSV 文件
"""

from __future__ import annotations

import csv
from typing import Any

from agent.tool_registry import Tool
from db.database import Database

CSV_HEADERS = [
    "title", "company", "city", "salary_min", "salary_max",
    "match_score", "greeting", "status", "applied_at",
]


class ExportCSVTool(Tool):
    """导出投递记录为 CSV 文件。"""

    @property
    def name(self) -> str:
        return "export_csv"

    @property
    def description(self) -> str:
        return "导出投递记录为 CSV"

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
                "output_path": {"type": "string", "description": "输出文件路径"},
            },
            "required": ["output_path"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db: Database = context["db"]
        output_path = params["output_path"]

        rows = await db.execute(
            "SELECT j.title, j.company, j.city, j.salary_min, j.salary_max, "
            "j.match_score, a.greeting, a.status, a.applied_at "
            "FROM applications a JOIN jobs j ON a.job_id = j.id "
            "ORDER BY a.id"
        )

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
            for row in rows:
                writer.writerow([row[h] for h in CSV_HEADERS])

        return {
            "success": True,
            "path": output_path,
            "row_count": len(rows),
        }
