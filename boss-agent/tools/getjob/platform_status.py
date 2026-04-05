"""
PlatformStatusTool — 查询 getjob 平台状态（登录 + 任务运行）
"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool
from services.getjob_client import CONNECTION_REFUSED_MARKER

_SERVICE_DOWN_MSG = (
    "getjob 服务未启动，请先运行 getjob"
    "（cd reference-crawler && ./gradlew bootRun，端口 8888）"
)

VALID_PLATFORMS = ("liepin", "zhilian")


class PlatformStatusTool(Tool):
    @property
    def name(self) -> str:
        return "platform_status"

    @property
    def description(self) -> str:
        return "查询 getjob 平台状态：是否已登录、是否有任务在运行。支持 liepin / zhilian。"

    @property
    def category(self) -> str:
        return "getjob"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["liepin", "zhilian"],
                    "description": "平台名称",
                },
            },
            "required": ["platform"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        platform = params.get("platform", "")
        if platform not in VALID_PLATFORMS:
            return {"success": False, "error": f"不支持的平台: {platform}，请使用 liepin 或 zhilian"}

        client = context["getjob_client"]
        result = await client.get_status(platform)

        if not result["success"]:
            if result.get("error") and CONNECTION_REFUSED_MARKER in result["error"]:
                return {"success": False, "error": _SERVICE_DOWN_MSG}
            return result

        return {"success": True, "data": result["data"]}
