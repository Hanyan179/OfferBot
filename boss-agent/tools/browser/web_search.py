"""
WebSearchTool — 网页搜索工具

搜索互联网信息，调用搜索引擎 API 返回结构化 SearchResult 列表。
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from agent.tool_registry import Tool


# ---------------------------------------------------------------------------
# 纯函数（辅助）
# ---------------------------------------------------------------------------


def validate_query(query: str) -> bool:
    """校验搜索关键词非空且非纯空白。"""
    return isinstance(query, str) and len(query.strip()) > 0


def clamp_max_results(value: int | None, default: int = 10) -> int:
    """规范化 max_results 到 [1, 20] 范围。"""
    if value is None:
        return max(1, min(20, default))
    try:
        v = int(value)
    except (TypeError, ValueError):
        return max(1, min(20, default))
    return max(1, min(20, v))


def parse_search_response(raw_response: dict) -> list[dict]:
    """解析搜索引擎 API 原始响应为 SearchResult 列表。

    期望 raw_response 格式:
    {
        "webPages": {
            "value": [
                {"name": "...", "url": "...", "snippet": "..."},
                ...
            ]
        }
    }
    """
    pages = raw_response.get("webPages", {})
    items = pages.get("value", [])
    results: list[dict] = []
    for item in items:
        results.append({
            "title": item.get("name", ""),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", ""),
        })
    return results


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------

_DEFAULT_SEARCH_RESULTS = 10
_DEFAULT_SEARCH_API_KEY = ""
_SEARCH_API_BASE = "https://api.bing.microsoft.com/v7.0/search"


class WebSearchTool(Tool):
    """网页搜索工具：搜索关键词 → 调用搜索 API → 返回结构化结果。"""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "搜索互联网信息，返回结构化搜索结果。"
            "支持搜索公司背景、技术面试题、行业动态等。"
        )

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
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {
                    "type": "integer",
                    "description": "最大返回结果数（1-20，默认 10）",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        }

    def __init__(self, config: Any | None = None) -> None:
        self._config = config
        self._default_results = getattr(
            config, "web_search_default_results", _DEFAULT_SEARCH_RESULTS
        )
        self._api_key: str = getattr(
            config, "web_search_api_key", _DEFAULT_SEARCH_API_KEY
        )

    async def execute(self, params: dict, context: Any) -> dict:
        query: str = params.get("query", "")
        max_results_raw = params.get("max_results")

        # 1. 校验 query
        if not validate_query(query):
            return {
                "success": False,
                "error": "搜索关键词不能为空或纯空白字符",
                "metadata": {"query": query, "result_count": 0, "duration_ms": 0},
            }

        # 2. 规范化 max_results
        max_results = clamp_max_results(max_results_raw, self._default_results)

        # 3. 检查 API Key
        if not self._api_key:
            return {
                "success": False,
                "error": "搜索引擎 API Key 未配置（web_search_api_key）",
                "metadata": {"query": query, "result_count": 0, "duration_ms": 0},
            }

        # 4. 调用搜索引擎 API
        start = time.time()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    _SEARCH_API_BASE,
                    params={"q": query, "count": max_results},
                    headers={"Ocp-Apim-Subscription-Key": self._api_key},
                    timeout=30,
                )
        except httpx.TimeoutException:
            duration_ms = (time.time() - start) * 1000
            return {
                "success": False,
                "error": f"搜索引擎 API 请求超时: {query}",
                "metadata": {"query": query, "result_count": 0, "duration_ms": duration_ms},
            }
        except httpx.HTTPError as exc:
            duration_ms = (time.time() - start) * 1000
            return {
                "success": False,
                "error": f"搜索引擎 API 错误: {exc}",
                "metadata": {"query": query, "result_count": 0, "duration_ms": duration_ms},
            }

        duration_ms = (time.time() - start) * 1000

        # 5. 非 2xx
        if resp.status_code < 200 or resp.status_code >= 300:
            return {
                "success": False,
                "error": f"搜索引擎 API 不可用: {resp.status_code} {resp.reason_phrase}",
                "metadata": {"query": query, "result_count": 0, "duration_ms": duration_ms},
            }

        # 6. 解析结果
        try:
            raw = resp.json()
        except Exception:
            return {
                "success": False,
                "error": "搜索引擎 API 返回格式异常",
                "metadata": {"query": query, "result_count": 0, "duration_ms": duration_ms},
            }

        results = parse_search_response(raw)

        # 7. 截断到 max_results
        results = results[:max_results]

        return {
            "success": True,
            "results": results,
            "metadata": {
                "query": query,
                "result_count": len(results),
                "duration_ms": duration_ms,
            },
        }
