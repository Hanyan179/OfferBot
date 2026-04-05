"""爬取岗位详情页 JD 并写回数据库。"""

from __future__ import annotations
from typing import Any
from agent.tool_registry import Tool


class FetchJobDetailTool(Tool):
    """通过 getjob 服务爬取猎聘岗位详情页，获取完整 JD。"""

    @property
    def name(self) -> str:
        return "fetch_job_detail"

    @property
    def display_name(self) -> str:
        return "爬取岗位详情"

    @property
    def description(self) -> str:
        return "爬取指定岗位的详情页，获取完整 JD（职位描述、技能要求、职责等）。需要 getjob 服务运行且已登录猎聘。"

    @property
    def category(self) -> str:
        return "getjob"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "本地数据库中的岗位 ID",
                },
                "url": {
                    "type": "string",
                    "description": "岗位详情页 URL（如果不传 job_id，直接用 URL）",
                },
            },
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db = context.get("db") if isinstance(context, dict) else None
        client = context.get("getjob_client") if isinstance(context, dict) else None

        if client is None:
            return {"success": False, "error": "getjob 服务未配置"}

        url = params.get("url", "")
        job_id = params.get("job_id")

        # 如果传了 job_id，从数据库查 URL
        if not url and job_id and db:
            rows = await db.execute("SELECT url FROM jobs WHERE id = ?", (job_id,))
            if rows:
                url = rows[0]["url"]

        if not url:
            return {"success": False, "error": "需要提供 job_id 或 url"}

        # 调 getjob 服务爬取详情
        result = await client.fetch_job_detail("liepin", url)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "爬取失败")}

        jd_text = result.get("data", {}).get("jd", "")
        if not jd_text:
            return {"success": False, "error": "未能提取 JD 内容"}

        # 写回数据库
        if db and job_id:
            await db.execute_write(
                "UPDATE jobs SET raw_jd = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (jd_text, job_id),
            )

        return {
            "success": True,
            "job_id": job_id,
            "url": url,
            "jd_length": len(jd_text),
            "jd_preview": jd_text[:300],
        }
