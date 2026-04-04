"""
WebSearchTool — 网页搜索工具

使用 DashScope 千问的联网搜索功能（enable_search），
复用已有的 LLM API Key，不需要额外配置搜索引擎 Key。
"""

from __future__ import annotations

import time
from typing import Any

from agent.tool_registry import Tool


def validate_query(query: str) -> bool:
    return isinstance(query, str) and len(query.strip()) > 0


class WebSearchTool(Tool):
    """网页搜索工具：使用千问联网搜索，复用 LLM API Key，无需额外配置。"""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "搜索互联网最新信息并返回结果摘要。支持搜索公司背景、技术趋势、薪资水平、行业动态等。"

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

        start = time.time()
        try:
            # 从 context 获取 LLM client，复用已有的 API Key
            from agent.llm_client import LLMClient
            llm: LLMClient | None = None

            if isinstance(context, dict):
                # 尝试从 executor 获取
                executor = context.get("executor")
                if executor and hasattr(executor, "_llm"):
                    llm = executor._llm

            if llm is None:
                # fallback: 从 config 创建
                from config import load_config
                cfg = load_config()
                if not cfg.dashscope_api_key:
                    return {"success": False, "error": "未配置 LLM API Key，无法执行搜索"}
                llm = LLMClient(
                    api_key=cfg.dashscope_api_key,
                    model=cfg.dashscope_llm_model,
                    base_url=cfg.api_base_url,
                )

            # 调用千问联网搜索
            response = await llm.chat(
                messages=[{"role": "user", "content": query}],
                extra_body={"enable_search": True, "enable_thinking": False},
            )

            duration_ms = (time.time() - start) * 1000

            return {
                "success": True,
                "content": response,
                "metadata": {
                    "query": query,
                    "duration_ms": round(duration_ms, 1),
                    "source": "dashscope_web_search",
                },
            }

        except Exception as exc:
            duration_ms = (time.time() - start) * 1000
            return {
                "success": False,
                "error": f"搜索失败: {exc}",
                "metadata": {"query": query, "duration_ms": round(duration_ms, 1)},
            }
