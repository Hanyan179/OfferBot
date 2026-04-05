"""
GetjobServiceManagerTool — 启动/停止 getjob 服务进程

让 AI Agent 能自动管理 getjob 的生命周期，不需要用户手动在终端操作。
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path
from typing import Any

from agent.tool_registry import Tool
from services.getjob_client import GetjobClient, CONNECTION_REFUSED_MARKER

logger = logging.getLogger(__name__)

# getjob 项目路径（相对于 workspace 根目录）
_GETJOB_DIR = Path(__file__).resolve().parent.parent.parent.parent / "reference-crawler"

_SERVICE_STARTUP_MSG = "getjob 服务启动中，请稍等..."


class GetjobServiceManagerTool(Tool):
    """管理 getjob 服务的启动和停止。"""

    # 类级别保存进程引用
    _process: asyncio.subprocess.Process | None = None

    @property
    def name(self) -> str:
        return "getjob_service_manage"

    @property
    def display_name(self) -> str:
        return "管理爬虫服务"

    @property
    def description(self) -> str:
        return (
            "管理 getjob 爬虫服务的启动和停止。"
            "action=start 启动服务（后台运行），action=stop 停止服务，action=check 检查是否在运行。"
            "getjob 服务启动后会自动打开浏览器，用户需要在浏览器中扫码登录猎聘。"
        )

    @property
    def category(self) -> str:
        return "getjob"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "check"],
                    "description": "start=启动服务, stop=停止服务, check=检查状态",
                },
            },
            "required": ["action"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        action = params.get("action", "check")

        if action == "check":
            return await self._check(context)
        elif action == "start":
            return await self._start(context)
        elif action == "stop":
            return await self._stop()
        else:
            return {"success": False, "error": f"未知 action: {action}"}

    async def _check(self, context: Any) -> dict:
        """检查 getjob 服务是否在运行。"""
        client: GetjobClient = context["getjob_client"]
        r = await client.health_check()
        if r["success"]:
            return {"success": True, "running": True, "message": "getjob 服务正在运行"}
        return {"success": True, "running": False, "message": "getjob 服务未运行"}

    async def _start(self, context: Any) -> dict:
        """启动 getjob 服务。"""
        # 先检查是否已经在运行
        client: GetjobClient = context["getjob_client"]
        r = await client.health_check()
        if r["success"]:
            return {"success": True, "message": "getjob 服务已经在运行中"}

        # 检查 getjob 目录是否存在
        if not _GETJOB_DIR.exists():
            return {
                "success": False,
                "error": f"getjob 项目目录不存在: {_GETJOB_DIR}",
            }

        gradlew = _GETJOB_DIR / "gradlew"
        if not gradlew.exists():
            return {
                "success": False,
                "error": f"gradlew 不存在: {gradlew}",
            }

        # 启动后台进程
        try:
            GetjobServiceManagerTool._process = await asyncio.create_subprocess_exec(
                str(gradlew), "bootRun",
                cwd=str(_GETJOB_DIR),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            logger.info("getjob 进程已启动, PID=%s", GetjobServiceManagerTool._process.pid)
        except Exception as e:
            return {"success": False, "error": f"启动 getjob 失败: {e}"}

        # 等待服务就绪（最多 60 秒）
        for i in range(12):
            await asyncio.sleep(5)
            r = await client.health_check()
            if r["success"]:
                return {
                    "success": True,
                    "message": "getjob 服务已启动，浏览器已打开。请在浏览器中扫码登录猎聘。",
                    "pid": GetjobServiceManagerTool._process.pid,
                }

        return {
            "success": False,
            "error": "getjob 服务启动超时（60秒），请检查 reference-crawler 目录和 Java 环境",
        }

    async def _stop(self) -> dict:
        """停止 getjob 服务。"""
        proc = GetjobServiceManagerTool._process
        if proc is None:
            return {"success": True, "message": "没有由 agent 启动的 getjob 进程"}

        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
            GetjobServiceManagerTool._process = None
            return {"success": True, "message": "getjob 服务已停止"}
        except Exception as e:
            return {"success": False, "error": f"停止 getjob 失败: {e}"}
