"""
PlatformStartTaskTool / PlatformStopTaskTool — 启动/停止 getjob 任务
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


def _check_platform(platform: str) -> dict | None:
    if platform not in VALID_PLATFORMS:
        return {"success": False, "error": f"不支持的平台: {platform}，请使用 liepin 或 zhilian"}
    return None


def _handle_error(result: dict) -> dict:
    if result.get("error") and CONNECTION_REFUSED_MARKER in result["error"]:
        return {"success": False, "error": _SERVICE_DOWN_MSG}
    return result


class PlatformStartTaskTool(Tool):
    @property
    def name(self) -> str:
        return "platform_start_task"

    @property
    def display_name(self) -> str:
        return "启动平台任务"

    @property
    def description(self) -> str:
        return (
            "启动猎聘平台岗位爬取。不直接执行，而是生成操作卡片供用户确认参数后执行。"
            "AI 根据用户需求填写搜索参数（关键词、城市、薪资等），用户在 UI 上确认或修改后点击执行。"
        )

    @property
    def category(self) -> str:
        return "getjob"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["liepin"], "description": "平台名称（目前仅支持猎聘）"},
                "keywords": {"type": "string", "description": "搜索关键词，逗号分隔（如 'AI Agent工程师,全栈开发'）"},
                "city": {"type": "string", "description": "城市名称（如 上海、北京）"},
                "salaryCode": {"type": "string", "description": "薪资代码：1=10万以下,2=10-15万,3=15-20万,4=20-30万,5=30-50万,6=50-100万,7=100万以上"},
                "workYearCode": {"type": "string", "description": "工作年限：0=不限,1$3=1-3年,3$5=3-5年,5$10=5-10年,10$99=10年以上"},
                "eduLevel": {"type": "string", "description": "学历：000=不限,030=大专,040=本科,050=硕士,060=博士"},
                "maxPages": {"type": "integer", "description": "最大页数，默认3"},
                "maxItems": {"type": "integer", "description": "最大岗位数，默认100"},
            },
            "required": ["platform"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        platform = params.get("platform", "liepin")
        if err := _check_platform(platform):
            return err

        # 构建操作卡片，不直接执行
        city_options = [
            {"value": "全国", "label": "全国"}, {"value": "北京", "label": "北京"},
            {"value": "上海", "label": "上海"}, {"value": "天津", "label": "天津"},
            {"value": "重庆", "label": "重庆"}, {"value": "广州", "label": "广州"},
            {"value": "深圳", "label": "深圳"}, {"value": "苏州", "label": "苏州"},
            {"value": "南京", "label": "南京"}, {"value": "杭州", "label": "杭州"},
            {"value": "大连", "label": "大连"}, {"value": "成都", "label": "成都"},
            {"value": "武汉", "label": "武汉"}, {"value": "西安", "label": "西安"},
        ]
        salary_options = [
            {"value": "1", "label": "10万以下"}, {"value": "2", "label": "10-15万"},
            {"value": "3", "label": "15-20万"}, {"value": "4", "label": "20-30万"},
            {"value": "5", "label": "30-50万"}, {"value": "6", "label": "50-100万"},
            {"value": "7", "label": "100万以上"},
        ]
        work_year_options = [
            {"value": "0", "label": "不限"}, {"value": "1$3", "label": "1-3年"},
            {"value": "3$5", "label": "3-5年"}, {"value": "5$10", "label": "5-10年"},
            {"value": "10$99", "label": "10年以上"},
        ]
        edu_options = [
            {"value": "000", "label": "不限"}, {"value": "030", "label": "大专"},
            {"value": "040", "label": "本科"}, {"value": "050", "label": "硕士"},
            {"value": "060", "label": "博士"},
        ]

        return {
            "action": "confirm_required",
            "card_type": "start_task",
            "title": "🚀 启动岗位爬取",
            "description": "将在猎聘平台搜索以下条件的岗位（仅爬取，不投递）",
            "fields": [
                {"id": "keywords", "label": "搜索关键词", "type": "text", "value": params.get("keywords", ""), "required": True},
                {"id": "city", "label": "城市", "type": "select", "options": city_options, "value": params.get("city", "上海")},
                {"id": "salaryCode", "label": "薪资范围", "type": "select", "options": salary_options, "value": params.get("salaryCode", "5")},
                {"id": "workYearCode", "label": "工作年限", "type": "select", "options": work_year_options, "value": params.get("workYearCode", "3$5")},
                {"id": "eduLevel", "label": "学历要求", "type": "select", "options": edu_options, "value": params.get("eduLevel", "040")},
                {"id": "maxPages", "label": "最大页数", "type": "number", "value": params.get("maxPages", 3)},
                {"id": "maxItems", "label": "最大岗位数", "type": "number", "value": params.get("maxItems", 100)},
            ],
            "status": "pending",
        }


class PlatformStopTaskTool(Tool):
    @property
    def name(self) -> str:
        return "platform_stop_task"

    @property
    def display_name(self) -> str:
        return "停止平台任务"

    @property
    def description(self) -> str:
        return "停止 getjob 平台正在运行的任务。支持 liepin / zhilian。"

    @property
    def category(self) -> str:
        return "getjob"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["liepin", "zhilian"], "description": "平台名称"},
            },
            "required": ["platform"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        platform = params.get("platform", "")
        if err := _check_platform(platform):
            return err

        client = context["getjob_client"]
        result = await client.stop_task(platform)

        # 停止后台轮询
        task_monitor = context.get("task_monitor") if isinstance(context, dict) else None
        if task_monitor:
            task_monitor.stop_all()

        if not result["success"]:
            error_text = result.get("error", "")
            if "没有正在运行" in error_text or "not running" in error_text.lower():
                return {"success": True, "message": f"{platform} 当前没有运行中的任务"}
            return _handle_error(result)

        return {"success": True, "data": result["data"], "message": f"{platform} 任务已停止"}
