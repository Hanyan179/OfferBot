"""
WebSearchTool — 网页搜索工具

使用当前已配置的 LLM 的联网搜索功能（千问 enable_search）。
直接复用 Executor 的 LLM Client，不需要额外配置。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agent.tool_registry import Tool

logger = logging.getLogger(__name__)


def validate_query(query: str) -> bool:
    return isinstance(query, str) and len(query.strip()) > 0


class WebSearchTool(Tool):
    """网页搜索工具：复用已配置的 LLM 进行联网搜索，无需额外配置。"""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "搜索互联网最新信息。支持搜索公司背景、技术趋势、薪资水平、行业动态等。"

    @property
    def category(self) -> str:
        return "browser"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词/问题"},
            },
            "required": ["query"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        query: str = params.get("query", "")
        if not validate_query(query):
            return {"success": False, "error": "搜索关键词不能为空"}

        # 从 context 获取 llm_client（由 Executor 传入）
        llm_client = None
        if isinstance(context, dict):
            llm_client = context.get("llm_client")

        if llm_client is None:
            return {"success": False, "error": "LLM 未初始化，请先在设置中配置 API Key"}

        start = time.time()
        try:
            response = await llm_client.chat(
                messages=[{"role": "user", "content": query}],
                extra_body={"enable_search": True, "enable_thinking": False},
            )
            duration_ms = (time.time() - start) * 1000
            return {
                "success": True,
                "content": response,
                "metadata": {"query": query, "duration_ms": round(duration_ms, 1)},
            }
        except Exception as exc:
            duration_ms = (time.time() - start) * 1000
            return {
                "success": False,
                "error": f"搜索失败: {exc}",
                "metadata": {"query": query, "duration_ms": round(duration_ms, 1)},
            }
