"""
FetchDetailTool — Playwright 直接获取猎聘岗位 JD 详情

替代原 FetchJobDetailTool（HTTP 调 Java getjob）。
入参和返回值格式不变。
"""

from __future__ import annotations

import logging
from typing import Any

from agent.tool_registry import Tool, ensure_list

logger = logging.getLogger(__name__)


class FetchDetailTool(Tool):
    @property
    def name(self) -> str:
        return "fetch_job_detail"

    @property
    def toolset(self) -> str:
        return "crawl"

    @property
    def display_name(self) -> str:
        return "获取岗位详情"

    @property
    def description(self) -> str:
        return (
            "获取指定岗位的详情页，获取完整 JD 并保存到本地数据库。"
            "传入本地数据库的岗位 ID。支持单个 job_id 或 job_ids 数组。"
        )

    @property
    def category(self) -> str:
        return "crawler"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "job_id": {"type": "integer", "description": "岗位 ID（单个）"},
                "job_ids": {"type": "array", "items": {"type": "integer"}, "description": "岗位 ID 列表（最多 10 个）"},
                "force": {"type": "boolean", "description": "强制重新获取", "default": False},
                "confirm": {
                    "type": "boolean",
                    "description": "是否弹出确认卡片。用户明确要求时 true；AI 自动执行时 false",
                    "default": True,
                },
            },
        }

    async def execute(self, params: dict, context: Any) -> dict:
        browser = context.get("browser")
        db = context.get("db")
        if not browser:
            return {"success": False, "error": "浏览器未初始化"}
        if not db:
            return {"success": False, "error": "数据库未配置"}

        job_ids = ensure_list(params.get("job_ids"), int)
        if not job_ids:
            job_ids = ensure_list(params.get("job_id"), int)
        job_ids = job_ids[:10]
        if not job_ids:
            return {"success": False, "error": "请提供 job_id 或 job_ids"}

        force = params.get("force", False)

        ph = ",".join("?" * len(job_ids))
        rows = await db.execute(
            f"SELECT id, url, title, company, raw_jd,"
            f" CASE WHEN salary_min IS NOT NULL THEN salary_min||'-'||salary_max||'K' ELSE '面议' END as salary"
            f" FROM jobs WHERE id IN ({ph})",
            tuple(job_ids),
        )
        if not rows:
            return {"success": False, "error": f"未找到 ID 为 {job_ids} 的岗位"}

        if not params.get("confirm", True):
            return await self._do_fetch(rows, force, db, browser)

        # 返回确认卡片
        jobs = [{
            "id": r["id"], "title": r.get("title", ""),
            "company": r.get("company", ""), "salary": r.get("salary", ""),
            "has_jd": bool(r.get("raw_jd")),
        } for r in rows]

        return {
            "action": "confirm_required",
            "card_type": "fetch_detail",
            "title": "📄 获取岗位详情",
            "description": f"将爬取 {len(jobs)} 个岗位的完整 JD（已有 JD 的会跳过）",
            "fields": [],
            "jobs": jobs,
            "params": {"force": force},
            "status": "pending",
        }

    @staticmethod
    async def _do_fetch(rows, force: bool, db, browser) -> dict:
        success_count = 0
        fail_count = 0
        skipped_count = 0
        results = []

        for row in rows:
            url = row.get("url", "")
            local_id = row["id"]
            title = row.get("title", "")
            raw_jd = row.get("raw_jd") or ""

            if raw_jd and not force:
                skipped_count += 1
                results.append({"id": local_id, "title": title, "source": "cache"})
                continue
            if not url or url == "#":
                fail_count += 1
                continue

            jd_text = await browser.fetch_job_detail(url)
            if jd_text:
                await db.execute_write(
                    "UPDATE jobs SET raw_jd = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (jd_text, local_id),
                )
                success_count += 1
                results.append({"id": local_id, "title": title, "jd_preview": jd_text[:200]})
            else:
                fail_count += 1

        return {
            "success": success_count > 0 or skipped_count > 0,
            "fetched": success_count,
            "skipped": skipped_count,
            "failed": fail_count,
            "results": results,
        }
