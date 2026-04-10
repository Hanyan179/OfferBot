"""
ScrapeJobsTool — Playwright 直接搜索猎聘，结果写入本地 jobs 表

替代原 SyncJobsTool（HTTP 调 Java getjob），Tool name 保持 sync_jobs 不变。
"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool
from tools.crawler.job_mapping import map_liepin, upsert_jobs


class ScrapeJobsTool(Tool):
    @property
    def name(self) -> str:
        return "sync_jobs"

    @property
    def toolset(self) -> str:
        return "crawl"

    @property
    def display_name(self) -> str:
        return "采集岗位列表"

    @property
    def description(self) -> str:
        return "通过浏览器自动化搜索猎聘岗位，结果直接写入本地数据库。"

    @property
    def category(self) -> str:
        return "crawler"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["liepin"], "description": "平台名称"},
                "keyword": {"type": "string", "description": "搜索关键词"},
                "city_code": {"type": "string", "description": "城市编码"},
                "salary_code": {"type": "string", "description": "薪资编码"},
                "max_pages": {"type": "integer", "description": "最大页数", "default": 2},
                "max_items": {"type": "integer", "description": "最大条数", "default": 100},
            },
            "required": ["platform"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        browser = context.get("browser")
        db = context.get("db")
        if not browser:
            return {"success": False, "error": "浏览器未初始化"}
        if not db:
            return {"success": False, "error": "数据库未配置"}

        keyword = params.get("keyword", "")
        items = await browser.search_jobs(
            keyword=keyword,
            city_code=params.get("city_code", ""),
            salary_code=params.get("salary_code", ""),
            max_pages=params.get("max_pages", 2),
            max_items=params.get("max_items", 100),
        )

        if not items:
            return {"success": True, "data": {"platform": "liepin", "total_fetched": 0, "inserted": 0, "updated": 0}}

        rows = [map_liepin(item) for item in items]
        inserted, updated = await upsert_jobs(db, rows)

        return {
            "success": True,
            "data": {
                "platform": "liepin",
                "total_fetched": len(items),
                "inserted": inserted,
                "updated": updated,
            },
        }
