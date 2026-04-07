"""
GetjobClient — getjob 服务 HTTP 客户端

封装所有 getjob REST API 调用，统一错误处理。
所有方法返回 {"success": bool, "data": ..., "error": str | None}。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 连接拒绝错误关键词，Tool 层据此返回统一提示
CONNECTION_REFUSED_MARKER = "无法连接 getjob 服务"


class GetjobClient:
    """getjob 服务 HTTP 客户端"""

    def __init__(self, base_url: str = "http://localhost:8888") -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        )

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> dict:
        """统一请求封装，所有异常包装为 success=False。"""
        try:
            resp = await self._client.request(method, path, **kwargs)
            if resp.status_code >= 400:
                try:
                    body = resp.text
                except Exception:
                    body = ""
                if resp.status_code >= 500:
                    return {"success": False, "data": None, "error": f"getjob 服务内部错误: {body}", "status_code": resp.status_code}
                return {"success": False, "data": None, "error": f"HTTP {resp.status_code}: {body}", "status_code": resp.status_code}
            try:
                data = resp.json()
            except Exception:
                raw = resp.text[:200] if resp.text else ""
                return {"success": False, "data": None, "error": f"响应格式异常: {raw}"}
            return {"success": True, "data": data, "error": None}
        except httpx.ConnectError:
            return {"success": False, "data": None, "error": f"{CONNECTION_REFUSED_MARKER} ({self._base_url})"}
        except httpx.ConnectTimeout:
            return {"success": False, "data": None, "error": f"连接 getjob 服务超时 ({self._base_url})"}
        except httpx.ReadTimeout:
            return {"success": False, "data": None, "error": "getjob 服务响应超时"}
        except httpx.TimeoutException as exc:
            return {"success": False, "data": None, "error": f"请求超时: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "data": None, "error": f"请求异常: {exc}"}

    @staticmethod
    def _build_filter_params(
        *,
        page: int | None = None,
        size: int | None = None,
        statuses: list[str] | None = None,
        location: str | None = None,
        experience: str | None = None,
        degree: str | None = None,
        minK: float | None = None,
        maxK: float | None = None,
        keyword: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if page is not None:
            params["page"] = page
        if size is not None:
            params["size"] = size
        if statuses:
            params["statuses"] = ",".join(statuses)
        if location:
            params["location"] = location
        if experience:
            params["experience"] = experience
        if degree:
            params["degree"] = degree
        if minK is not None:
            params["minK"] = minK
        if maxK is not None:
            params["maxK"] = maxK
        if keyword:
            params["keyword"] = keyword
        return params

    # ------------------------------------------------------------------
    # 全局
    # ------------------------------------------------------------------

    async def health_check(self) -> dict:
        """检测 getjob 服务全局健康状态。"""
        return await self._request("GET", "/api/health")

    # ------------------------------------------------------------------
    # 平台通用方法
    # ------------------------------------------------------------------

    async def login_status(self, platform: str) -> dict:
        return await self._request("GET", f"/api/{platform}/login-status")

    async def get_status(self, platform: str) -> dict:
        return await self._request("GET", f"/api/{platform}/status")

    async def start_task(self, platform: str) -> dict:
        return await self._request("POST", f"/api/{platform}/start")

    async def stop_task(self, platform: str) -> dict:
        return await self._request("POST", f"/api/{platform}/stop")

    async def get_config(self, platform: str) -> dict:
        return await self._request("GET", f"/api/{platform}/config")

    async def update_config(self, platform: str, config: dict) -> dict:
        return await self._request("PUT", f"/api/{platform}/config", json=config)

    async def get_job_list(self, platform: str, **filters: Any) -> dict:
        params = self._build_filter_params(**filters)
        return await self._request("GET", f"/api/{platform}/list", params=params)

    async def fetch_job_detail(self, platform: str, url: str) -> dict:
        """获取单个岗位详情页 JD。超时 60s（浏览器加载慢）。"""
        return await self._request("GET", f"/api/{platform}/job-detail", params={"url": url},
                                   timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0))

    async def batch_fetch_detail(self, platform: str, limit: int = 10) -> dict:
        """批量获取岗位详情页 JD（从数据库取无 JD 的岗位）。"""
        return await self._request("POST", f"/api/{platform}/batch-detail", params={"limit": limit},
                                   timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0))

    async def get_stats(self, platform: str, **filters: Any) -> dict:
        params = self._build_filter_params(**filters)
        return await self._request("GET", f"/api/{platform}/stats", params=params)

    async def logout(self, platform: str) -> dict:
        return await self._request("POST", f"/api/{platform}/logout")

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()
