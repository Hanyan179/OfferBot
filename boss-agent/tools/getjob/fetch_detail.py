"""获取岗位详情页 JD 并写回数据库。

支持两种调用方式：
- 单个 job_id：从本地数据库查 URL，获取一个
- job_ids 数组：从本地数据库批量查 URL，逐个获取
"""

from __future__ import annotations

import logging
from typing import Any
from agent.tool_registry import Tool

logger = logging.getLogger(__name__)


class FetchJobDetailTool(Tool):
    """通过 getjob 服务获取猎聘岗位详情页，获取完整 JD。"""

    @property
    def name(self) -> str:
        return "fetch_job_detail"

    @property
    def toolset(self) -> str:
        return "crawl"

    @property
    def display_name(self) -> str:
        return "获取岗位详情"

    @property
    def description(self) -> str:
        return (
            "获取指定岗位的详情页，获取完整 JD 并保存到本地数据库。"
            "传入本地数据库的岗位 ID（从 query_jobs 返回的 id 字段获取）。"
            "支持单个 job_id 或 job_ids 数组批量获取。"
        )

    @property
    def category(self) -> str:
        return "getjob"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "integer",
                    "description": "本地数据库中的岗位 ID（单个）",
                },
                "job_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "本地数据库中的岗位 ID 列表（批量，最多 10 个）",
                },
                "force": {
                    "type": "boolean",
                    "description": "强制重新获取，忽略本地缓存",
                    "default": False,
                },
            },
        }

    async def execute(self, params: dict, context: Any) -> dict:
        db = context.get("db") if isinstance(context, dict) else None
        client = context.get("getjob_client") if isinstance(context, dict) else None

        if client is None:
            return {"success": False, "error": "getjob 服务未配置"}
        if db is None:
            return {"success": False, "error": "数据库未配置"}

        job_ids = params.get("job_ids") or []
        single_id = params.get("job_id")
        if single_id and not job_ids:
            job_ids = [single_id]

        if not job_ids:
            return {"success": False, "error": "请提供 job_id 或 job_ids"}

        # 强转为 int，过滤无效值（AI 可能传字符串、浮点数等）
        clean_ids = []
        for v in job_ids[:10]:
            try:
                clean_ids.append(int(v))
            except (ValueError, TypeError):
                pass
        job_ids = clean_ids

        if not job_ids:
            return {"success": False, "error": "job_ids 中没有有效的整数 ID"}

        force = params.get("force", False)

        # 从本地数据库查出 URL 和已有 raw_jd
        placeholders = ",".join("?" * len(job_ids))
        rows = await db.execute(
            f"SELECT id, url, title, raw_jd FROM jobs WHERE id IN ({placeholders})",
            tuple(job_ids),
        )

        if not rows:
            return {"success": False, "error": f"未找到 ID 为 {job_ids} 的岗位"}

        # 注册任务到全局状态（供前端任务面板显示）
        from services.task_state import TaskStateStore, TaskInfo
        import time as _time
        task_id = f"fetch-detail-{int(_time.time())}"
        store = TaskStateStore(db)
        await store.upsert(TaskInfo(
            task_id=task_id, name=f"爬取岗位详情（{len(rows)}条）",
            platform="liepin", status="running",
            progress_text=f"0/{len(rows)}",
        ))

        results = []
        success_count = 0
        fail_count = 0
        skipped_count = 0

        for row in rows:
            url = row.get("url", "")
            local_id = row["id"]
            title = row.get("title", "")
            raw_jd = row.get("raw_jd") or ""

            # 去重：raw_jd 非空且非 force 时跳过获取
            if raw_jd and not force:
                skipped_count += 1
                results.append({
                    "id": local_id, "title": title,
                    "jd_length": len(raw_jd),
                    "jd_preview": raw_jd[:200],
                    "source": "local_cache",
                })
                continue

            if not url or url == "#":
                fail_count += 1
                results.append({"id": local_id, "title": title, "error": "无 URL"})
                continue

            try:
                result = await client.fetch_job_detail("liepin", url)
                if result.get("success"):
                    jd_text = result.get("data", {}).get("jd", "")
                    if jd_text:
                        await db.execute_write(
                            "UPDATE jobs SET raw_jd = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (jd_text, local_id),
                        )
                        success_count += 1
                        results.append({
                            "id": local_id, "title": title,
                            "jd_length": len(jd_text),
                            "jd_preview": jd_text[:200],
                            "source": "remote",
                        })
                    else:
                        fail_count += 1
                        results.append({"id": local_id, "title": title, "error": "JD 为空"})
                else:
                    fail_count += 1
                    results.append({"id": local_id, "title": title, "error": result.get("error", "获取失败")})
            except Exception as e:
                fail_count += 1
                results.append({"id": local_id, "title": title, "error": str(e)})
                logger.warning("获取岗位详情失败: id=%s url=%s error=%s", local_id, url, e)

            # 更新任务进度
            done = success_count + fail_count + skipped_count
            await store.update_progress(task_id, f"{done}/{len(rows)} 成功{success_count} 失败{fail_count}")

        # 标记爬取任务完成
        await store.update_status(task_id, "completed" if success_count > 0 or skipped_count > 0 else "failed",
                            f"完成 成功{success_count} 跳过{skipped_count} 失败{fail_count}")

        return {
            "success": success_count > 0 or skipped_count > 0,
            "total": len(rows),
            "fetched": success_count,
            "skipped": skipped_count,
            "failed": fail_count,
            "results": results,
        }
