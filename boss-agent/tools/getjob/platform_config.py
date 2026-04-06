"""
PlatformGetConfigTool / PlatformUpdateConfigTool — 读写 getjob 平台配置
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


class PlatformGetConfigTool(Tool):
    @property
    def name(self) -> str:
        return "platform_get_config"

    @property
    def display_name(self) -> str:
        return "读取平台配置"

    @property
    def description(self) -> str:
        return "读取 getjob 平台当前配置（关键词、城市、薪资、scrapeOnly 等）。支持 liepin / zhilian。"

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
            },
            "required": ["platform"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        platform = params.get("platform", "")
        if err := _check_platform(platform):
            return err

        client = context["getjob_client"]
        result = await client.get_config(platform)

        if not result["success"]:
            return _handle_error(result)

        return {"success": True, "data": result["data"]}


class PlatformUpdateConfigTool(Tool):
    @property
    def name(self) -> str:
        return "platform_update_config"

    @property
    def display_name(self) -> str:
        return "更新平台配置"

    @property
    def description(self) -> str:
        return (
            "更新 getjob 平台搜索配置。支持 liepin / zhilian。"
            "keywords 用逗号分隔多个关键词（如 'AI Agent,全栈工程师'），每个关键词独立搜索。"
            "关键词要具体精准，避免太宽泛。"
        )

    @property
    def category(self) -> str:
        return "getjob"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["liepin", "zhilian"], "description": "平台名称"},
                "config": {
                    "type": "object",
                    "description": "要更新的配置字段（仅传需要修改的字段）",
                    "properties": {
                        "keywords": {"type": "string", "description": "搜索关键词，逗号分隔（如 'AI Agent工程师,全栈开发'），每个独立搜索"},
                        "city": {"type": "string", "description": "城市（猎聘用）"},
                        "cityCode": {"type": "string", "description": "城市编码（智联用）"},
                        "salaryCode": {"type": "string", "description": "猎聘薪资代码（1-7），一般不需要直接传，用 monthly_salary_min 自动换算"},
                        "monthly_salary_min": {"type": "integer", "description": "用户期望的最低月薪（单位K），会自动换算为猎聘年薪代码"},
                        "salary": {"type": "string", "description": "薪资范围（智联用）"},
                        "scrapeOnly": {"type": "boolean", "description": "仅爬取模式"},
                        "maxPages": {"type": "integer", "description": "最大爬取页数（默认3，建议不超过5）"},
                        "maxItems": {"type": "integer", "description": "最大爬取岗位数量（默认100）"},
                    },
                },
            },
            "required": ["platform", "config"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        platform = params.get("platform", "")
        if err := _check_platform(platform):
            return err

        config_data = params.get("config", {})
        if not config_data:
            return {"success": False, "error": "config 参数不能为空"}

        # 月薪→猎聘年薪代码自动换算
        monthly_min = config_data.pop("monthly_salary_min", None)
        if monthly_min is not None and "salaryCode" not in config_data:
            annual_wan = monthly_min * 12 / 10  # K月薪 → 万年薪（如30K → 36万）
            if annual_wan < 10:
                code = "1"
            elif annual_wan < 16:
                code = "2"
            elif annual_wan < 21:
                code = "3"
            elif annual_wan < 31:
                code = "4"
            elif annual_wan < 51:
                code = "5"
            elif annual_wan < 101:
                code = "6"
            else:
                code = "7"
            config_data["salaryCode"] = code

        client = context["getjob_client"]
        result = await client.update_config(platform, config_data)

        if not result["success"]:
            return _handle_error(result)

        # 返回时附上换算说明
        resp = {"success": True, "data": result["data"]}
        if monthly_min is not None:
            resp["salary_conversion"] = {
                "monthly_k": monthly_min,
                "annual_wan": monthly_min * 12 / 10,
                "liepin_code": config_data.get("salaryCode"),
            }
        return resp
