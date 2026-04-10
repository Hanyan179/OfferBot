"""对指定岗位执行投递打招呼，AI 生成定制化消息。"""

from __future__ import annotations

import logging
from typing import Any

from agent.tool_registry import Tool

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


class PlatformDeliverTool(Tool):
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
        return (
            "对指定岗位执行投递打招呼。"
            "会根据用户画像和岗位 JD 自动生成个性化打招呼语。"
            "传入本地数据库的岗位 ID 列表。"
        )

    @property
    def category(self) -> str:
        return "getjob"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["liepin"],
                    "description": "平台名称",
                },
                "job_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "本地数据库的岗位 ID 列表",
                },
            },
            "required": ["platform", "job_ids"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        client = context.get("getjob_client")
        if not client:
            return {"success": False, "error": "getjob 服务未配置"}

        db = context.get("db")
        llm_client = context.get("llm_client")
        platform = params.get("platform", "liepin")
        job_ids = params.get("job_ids")
        if not job_ids:
            return {"success": False, "error": "请提供 job_ids 列表"}

        # 查本地岗位数据
        placeholders = ",".join("?" * len(job_ids))
        jobs = await db.execute(
            f"SELECT id, title, company, raw_jd, url FROM jobs WHERE id IN ({placeholders})",
            tuple(job_ids),
        ) if db else []

        if not jobs:
            return {"success": False, "error": "未找到指定岗位"}

        # 获取用户画像摘要
        profile = ""
        if db:
            rows = await db.execute("SELECT name, skills, work_experience, self_intro FROM resumes LIMIT 1")
            if rows:
                r = rows[0]
                parts = [r.get("self_intro") or "", r.get("skills") or ""]
                profile = "\n".join(p for p in parts if p)[:500]

        # 为每个岗位生成打招呼语
        messages: dict[int, str] = {}
        if llm_client and profile:
            for job in jobs:
                jd = (job.get("raw_jd") or "")[:800]
                if not jd:
                    continue
                prompt = GREETING_PROMPT.format(
                    profile=profile,
                    title=job.get("title", ""),
                    company=job.get("company", ""),
                    jd=jd,
                )
                try:
                    resp = await llm_client.chat([{"role": "user", "content": prompt}])
                    text = resp.get("content", "").strip() if isinstance(resp, dict) else str(resp).strip()
                    if text and len(text) <= 200:
                        messages[job["id"]] = text
                        logger.info("生成打招呼语: job=%s msg=%s", job["id"], text[:50])
                except Exception as e:
                    logger.warning("生成打招呼语失败: job=%s error=%s", job["id"], e)

        # 需要 getjob 侧的 jobId（从 url 映射），目前直接传本地 job_ids
        # TODO: 本地 id → getjob id 映射
        try:
            result = await client.deliver(platform, job_ids, messages or None)
            return result
        except Exception as exc:
            logger.warning("投递失败: %s", exc)
            return {"success": False, "error": f"投递失败: {exc}"}
