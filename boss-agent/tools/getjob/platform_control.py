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
        return "启动 getjob 平台的自动投递/获取任务。支持 liepin / zhilian。"

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
        result = await client.start_task(platform)

        if not result["success"]:
            data = result.get("data") or {}
            if isinstance(data, dict) and data.get("status") == "running":
                return {"success": True, "data": data, "message": "任务已在运行中"}
            return _handle_error(result)

        # 启动后台轮询 + 完成回调（自动同步数据）
        task_monitor = context.get("task_monitor") if isinstance(context, dict) else None
        if task_monitor:
            import time
            task_id = f"{platform}-{int(time.time())}"

            async def _on_complete(p: str) -> dict:
                """任务完成后自动同步数据到本地"""
                from tools.getjob.platform_sync import SyncJobsTool
                db = context.get("db")
                if not db:
                    return {}
                tool = SyncJobsTool()
                return await tool.execute({"platform": p}, context)

            task_monitor.start_polling(
                task_id=task_id,
                platform=platform,
                client=client,
                on_complete=_on_complete,
                agent_busy_check=context.get("agent_busy_check"),
            )

        return {"success": True, "data": result["data"]}


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
