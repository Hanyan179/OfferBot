"""
PlatformStatsTool — 查询 getjob 平台投递统计
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


class PlatformStatsTool(Tool):
    @property
    def name(self) -> str:
        return "platform_stats"

    @property
    def toolset(self) -> str:
        return "admin"

    @property
    def display_name(self) -> str:
        return "平台投递统计"

    @property
    def description(self) -> str:
        return (
            "查询 getjob 平台投递统计数据（KPI 汇总 + 图表数据）。"
            "支持按状态、城市、经验、学历、薪资范围、关键词筛选。"
        )

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
                "platform": {"type": "string", "enum": ["liepin", "zhilian"], "description": "平台名称"},
                "statuses": {"type": "array", "items": {"type": "string"}, "description": "状态筛选"},
                "location": {"type": "string", "description": "城市筛选"},
                "experience": {"type": "string", "description": "经验筛选"},
                "degree": {"type": "string", "description": "学历筛选"},
                "minK": {"type": "number", "description": "薪资下限（K/月）"},
                "maxK": {"type": "number", "description": "薪资上限（K/月）"},
                "keyword": {"type": "string", "description": "关键词"},
            },
            "required": ["platform"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        platform = params.get("platform", "")
        if platform not in VALID_PLATFORMS:
            return {"success": False, "error": f"不支持的平台: {platform}，请使用 liepin 或 zhilian"}

        client = context["getjob_client"]

        # 构建筛选参数
        filters: dict[str, Any] = {}
        if statuses := params.get("statuses"):
            filters["statuses"] = statuses
        if location := params.get("location"):
            filters["location"] = location
        if experience := params.get("experience"):
            filters["experience"] = experience
        if degree := params.get("degree"):
            filters["degree"] = degree
        if (minK := params.get("minK")) is not None:
            filters["minK"] = minK
        if (maxK := params.get("maxK")) is not None:
            filters["maxK"] = maxK
        if keyword := params.get("keyword"):
            filters["keyword"] = keyword

        result = await client.get_stats(platform, **filters)

        if not result["success"]:
            if result.get("error") and CONNECTION_REFUSED_MARKER in result["error"]:
                return {"success": False, "error": _SERVICE_DOWN_MSG}
            return result

        return {"success": True, "data": result["data"]}
