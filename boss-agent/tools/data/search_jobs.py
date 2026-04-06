"""语义搜索岗位 — 基于向量检索匹配岗位实体。"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool


class SearchJobsTool(Tool):
    """通过语义检索匹配岗位，返回完整实体（含 url）。"""

    @property
    def name(self) -> str:
        return "search_jobs_semantic"

    @property
    def display_name(self) -> str:
        return "语义搜索岗位"

    @property
    def description(self) -> str:
        return (
            "用自然语言描述搜索岗位（如'AI Agent 架构方向'、'全栈工程化'）。"
            "基于 JD 内容的向量检索，返回语义最匹配的岗位列表（含链接）。"
            "前提：岗位需要已抓取详情（有 JD 数据）。"
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
                "query": {
                    "type": "string",
                    "description": "自然语言搜索描述（如'AI Agent 架构方向'、'人类是架构师的岗位'）",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回数量",
                    "default": 10,
                },
            },
            "required": ["query"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db = context.get("db") if isinstance(context, dict) else None
        job_index = context.get("job_index") if isinstance(context, dict) else None
        embed_fn = context.get("embed_fn") if isinstance(context, dict) else None

        if not job_index or not embed_fn:
            return {"success": False, "error": "向量索引未初始化，需要先抓取岗位详情"}

        query = params.get("query", "")
        top_k = params.get("top_k", 10)

        # 检索
        results = await job_index.search(query, embed_fn, top_k=top_k)
        if not results:
            return {
                "success": True,
                "count": 0,
                "jobs": [],
                "hint": "向量索引为空，需要先对岗位抓取详情（fetch_job_detail）后才能语义搜索。",
            }

        # 用 job_id 查完整实体
        ids = [r["job_id"] for r in results]
        scores = {r["job_id"]: r["score"] for r in results}
        placeholders = ",".join("?" * len(ids))
        rows = await db.execute(
            f"SELECT id, url, title, company, salary_min, salary_max, salary_months, city, experience, education FROM jobs WHERE id IN ({placeholders})",
            tuple(ids),
        )

        # 按相似度排序
        row_map = {r["id"]: r for r in rows}
        jobs = []
        for job_id in ids:
            if job_id in row_map:
                job = dict(row_map[job_id])
                job["relevance_score"] = round(scores.get(job_id, 0), 3)
                jobs.append(job)

        return {
            "success": True,
            "count": len(jobs),
            "jobs": jobs,
        }
