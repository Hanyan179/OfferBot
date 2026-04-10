"""
DeliverTool — Playwright 直接在猎聘投递打招呼

替代原 PlatformDeliverTool（HTTP 调 Java getjob）。
"""

from __future__ import annotations

import logging
from typing import Any

from agent.tool_registry import Tool, ensure_list

logger = logging.getLogger(__name__)

GREETING_PROMPT = """基于以下信息，生成一段简洁、自然的打招呼语（不超过80字）。
要求：体现求职者与岗位的匹配点，语气真诚专业，不要模板化。

【求职者画像】
{profile}

【岗位信息】
职位：{title}
公司：{company}
JD：{jd}

直接输出打招呼语，不要任何解释。"""


class DeliverTool(Tool):
    @property
    def name(self) -> str:
        return "platform_deliver"

    @property
    def toolset(self) -> str:
        return "deliver"

    @property
    def display_name(self) -> str:
        return "投递打招呼"

    @property
    def description(self) -> str:
        return "对指定岗位执行投递打招呼，会根据用户画像和 JD 自动生成个性化打招呼语。"

    @property
    def category(self) -> str:
        return "crawler"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["liepin"], "description": "平台名称"},
                "job_ids": {"type": "array", "items": {"type": "integer"}, "description": "岗位 ID 列表"},
            },
            "required": ["platform", "job_ids"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        browser = context.get("browser")
        db = context.get("db")
        if not browser:
            return {"success": False, "error": "浏览器未初始化"}

        llm_client = context.get("llm_client")
        job_ids = ensure_list(params.get("job_ids"), int)
        if not job_ids:
            return {"success": False, "error": "请提供 job_ids 列表"}

        ph = ",".join("?" * len(job_ids))
        jobs = await db.execute(
            f"SELECT id, title, company, raw_jd, url FROM jobs WHERE id IN ({ph})",
            tuple(job_ids),
        ) if db else []
        if not jobs:
            return {"success": False, "error": "未找到指定岗位"}

        # 获取用户画像
        profile = ""
        if db:
            rows = await db.execute("SELECT name, skills, work_experience, self_intro FROM resumes LIMIT 1")
            if rows:
                r = rows[0]
                parts = [r.get("self_intro") or "", r.get("skills") or ""]
                profile = "\n".join(p for p in parts if p)[:500]

        # 逐个投递
        delivered = 0
        failed = 0
        for job in jobs:
            url = job.get("url", "")
            if not url:
                failed += 1
                continue

            # 生成打招呼语
            msg = ""
            if llm_client and profile and job.get("raw_jd"):
                try:
                    prompt = GREETING_PROMPT.format(
                        profile=profile, title=job.get("title", ""),
                        company=job.get("company", ""), jd=(job.get("raw_jd") or "")[:800],
                    )
                    resp = await llm_client.chat([{"role": "user", "content": prompt}])
                    text = resp.get("content", "").strip() if isinstance(resp, dict) else str(resp).strip()
                    if text and len(text) <= 200:
                        msg = text
                except Exception as e:
                    logger.warning("生成打招呼语失败: %s", e)

            ok = await browser.deliver(url, msg)
            if ok:
                delivered += 1
            else:
                failed += 1

        return {"success": delivered > 0, "delivered": delivered, "failed": failed}
