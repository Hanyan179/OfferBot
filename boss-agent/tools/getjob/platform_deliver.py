"""对指定岗位执行投递打招呼。"""

from __future__ import annotations

import logging
from typing import Any

from agent.tool_registry import Tool

logger = logging.getLogger(__name__)


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
            "前提：岗位已获取并有详情数据。"
            "传入 getjob 平台侧的 job_ids 列表。"
            "需要 getjob 服务运行且已登录猎聘。"
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
                    "description": "要投递的岗位 ID 列表（getjob 平台侧）",
                },
            },
            "required": ["platform", "job_ids"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        client = context.get("getjob_client")
        if not client:
            return {"success": False, "error": "getjob 服务未配置"}

        platform = params.get("platform", "liepin")
        job_ids = params.get("job_ids")
        if not job_ids:
            return {"success": False, "error": "请提供 job_ids 列表"}

        try:
            result = await client.deliver(platform, job_ids)
            return result
        except Exception as exc:
            logger.warning("投递失败: %s", exc)
            return {"success": False, "error": f"投递失败: {exc}"}
