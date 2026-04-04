"""
WebFetchTool — 网页内容获取工具

抓取指定 URL 的 HTML 内容，使用 html2text 转换为 Markdown 格式返回。
支持 TTL 内存缓存、HTTP→HTTPS 自动升级、内容截断。
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import html2text
import httpx

from agent.tool_registry import Tool


# ---------------------------------------------------------------------------
# 纯函数（辅助）
# ---------------------------------------------------------------------------


def validate_url(url: str) -> bool:
    """校验 URL 格式：必须有 scheme 和 netloc。"""
    try:
        parsed = urlparse(url)
        return bool(parsed.scheme) and bool(parsed.netloc)
    except Exception:
        return False


def normalize_url(url: str) -> str:
    """URL 标准化：去除尾部空白，http→https 升级。"""
    url = url.strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url


def truncate_content(content: str, max_length: int) -> tuple[str, bool]:
    """截断内容到 *max_length* 字符。

    Returns:
        (截断后内容, 是否被截断)
    """
    if len(content) <= max_length:
        return content, False
    suffix = "\n\n[内容已截断]"
    cut = max_length - len(suffix)
    if cut < 0:
        cut = 0
    return content[:cut] + suffix, True


def html_to_markdown(html: str) -> str:
    """使用 html2text 将 HTML 转换为 Markdown。"""
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0  # 不自动换行
    return converter.handle(html)


# ---------------------------------------------------------------------------
# TTL 内存缓存
# ---------------------------------------------------------------------------


class TTLCache:
    """简单的 TTL 内存缓存（dict + timestamp）。"""

    def __init__(self, ttl_seconds: int = 900) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Any | None:
        """获取缓存值，过期或不存在返回 None。"""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, ts = entry
        if time.time() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        """写入缓存 + 当前时间戳。"""
        self._store[key] = (value, time.time())

    def clear_expired(self) -> None:
        """清理所有过期条目。"""
        now = time.time()
        expired = [k for k, (_, ts) in self._store.items() if now - ts > self._ttl]
        for k in expired:
            del self._store[k]


# ---------------------------------------------------------------------------
# WebFetchTool
# ---------------------------------------------------------------------------

# 默认值（可被 Config 覆盖）
_DEFAULT_TIMEOUT = 30
_DEFAULT_MAX_CONTENT_LENGTH = 50000
_DEFAULT_CACHE_TTL = 900


class WebFetchTool(Tool):
    """网页内容获取工具：抓取 URL → html2text 转 Markdown → 截断 → 返回。"""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "抓取指定 URL 的网页内容，转换为 Markdown 格式返回。"
            "支持查看岗位链接、公司页面、技术文档等。"
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
                "url": {"type": "string", "description": "要抓取的网页 URL"},
            },
            "required": ["url"],
        }

    def __init__(self, config: Any | None = None) -> None:
        self._config = config
        timeout = getattr(config, "web_fetch_timeout", _DEFAULT_TIMEOUT)
        max_len = getattr(config, "web_fetch_max_content_length", _DEFAULT_MAX_CONTENT_LENGTH)
        cache_ttl = getattr(config, "web_fetch_cache_ttl", _DEFAULT_CACHE_TTL)
        self._timeout = timeout
        self._max_content_length = max_len
        self._cache = TTLCache(ttl_seconds=cache_ttl)

    async def execute(self, params: dict, context: Any) -> dict:
        url: str = params.get("url", "")

        # 1. 校验 URL 格式
        if not validate_url(url):
            return {"success": False, "error": f"URL 格式不合法: {url}"}

        # 2. 标准化
        url = normalize_url(url)

        # 3. 检查缓存
        cached = self._cache.get(url)
        if cached is not None:
            return cached

        # 4. httpx 异步抓取
        start = time.time()
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.get(url, timeout=self._timeout)
        except httpx.TimeoutException:
            duration_ms = (time.time() - start) * 1000
            return {
                "success": False,
                "error": f"请求超时（{self._timeout}s）: {url}",
                "metadata": {"duration_ms": duration_ms, "final_url": url},
            }
        except httpx.HTTPError as exc:
            duration_ms = (time.time() - start) * 1000
            return {
                "success": False,
                "error": f"HTTP 请求错误: {exc}",
                "metadata": {"duration_ms": duration_ms, "final_url": url},
            }

        duration_ms = (time.time() - start) * 1000
        final_url = str(resp.url)

        # 5. 非 2xx
        if resp.status_code < 200 or resp.status_code >= 300:
            result = {
                "success": False,
                "error": f"HTTP {resp.status_code}: {resp.reason_phrase}",
                "metadata": {
                    "status_code": resp.status_code,
                    "duration_ms": duration_ms,
                    "final_url": final_url,
                },
            }
            return result

        # 6. html2text 转换
        raw_html = resp.text
        content_bytes = len(resp.content)
        try:
            markdown = html_to_markdown(raw_html)
        except Exception:
            markdown = raw_html  # 降级：返回原始文本

        # 7. 截断
        markdown, truncated = truncate_content(markdown, self._max_content_length)

        # 8. 组装结果
        result: dict[str, Any] = {
            "success": True,
            "content": markdown,
            "truncated": truncated,
            "metadata": {
                "status_code": resp.status_code,
                "content_bytes": content_bytes,
                "duration_ms": duration_ms,
                "final_url": final_url,
            },
        }

        # 9. 写入缓存
        self._cache.set(url, result)

        return result
