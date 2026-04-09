"""
TaskMonitor — 后台任务监控与通知队列

参考 Claude Code 的 messageQueueManager + task/framework 模式：
- 后台任务完成时，通知放入队列（不打断当前输出）
- executor 每轮工具执行完后，drain 队列注入到消息历史
- 如果 agent 不在 loop 中，直接推送给 UI

优先级：
- "next": 下一轮工具执行后立即 drain
- "later": 仅在显式 drain_all 时消费（预留）
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class NotificationPriority(str, Enum):
    next = "next"
    later = "later"


@dataclass
class TaskNotification:
    """一条任务通知"""
    task_id: str
    platform: str
    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    priority: NotificationPriority = NotificationPriority.next
    created_at: datetime = field(default_factory=datetime.now)


class TaskMonitor:
    """
    后台任务监控器。

    职责：
    1. 启动后台轮询，监控 getjob 任务状态
    2. 任务完成时放入通知队列
    3. 提供 drain 接口给 executor 消费
    """

    def __init__(self) -> None:
        self._queue: deque[TaskNotification] = deque()
        self._polling_tasks: dict[str, asyncio.Task] = {}
        self._ui_callback: Callable[[TaskNotification], Awaitable[None]] | None = None

    def set_ui_callback(self, callback: Callable[[TaskNotification], Awaitable[None]]) -> None:
        """设置 UI 推送回调（由 chat.py 注入）"""
        self._ui_callback = callback

    def enqueue(self, notification: TaskNotification) -> None:
        """入队一条通知"""
        logger.info("任务通知入队: task_id=%s platform=%s status=%s",
                     notification.task_id, notification.platform, notification.status)
        self._queue.append(notification)

    def drain(self, max_priority: NotificationPriority = NotificationPriority.next) -> list[TaskNotification]:
        """
        消费队列中符合优先级的通知。

        参考 Claude Code 的 getCommandsByMaxPriority：
        - NEXT: 只取 priority=NEXT 的
        - LATER: 取所有
        """
        threshold = list(NotificationPriority).index(max_priority)
        n = len(self._queue)
        drained: list[TaskNotification] = []
        for _ in range(n):
            notif = self._queue.popleft()
            if list(NotificationPriority).index(notif.priority) <= threshold:
                drained.append(notif)
            else:
                self._queue.append(notif)
        if drained:
            logger.info("drain 了 %d 条任务通知", len(drained))
        return drained

    def has_pending(self) -> bool:
        """是否有待消费的通知"""
        return len(self._queue) > 0

    def start_polling(
        self,
        task_id: str,
        platform: str,
        client: Any,
        poll_interval: float = 5.0,
        max_polls: int = 120,
        agent_busy_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[str, int, bool, str | None], Awaitable[None]] | None = None,
        on_complete: Callable[[str], Awaitable[dict]] | None = None,
    ) -> None:
        """启动后台轮询任务状态。"""
        task = asyncio.create_task(
            self._poll_loop(
                task_id, platform, client, poll_interval, max_polls,
                agent_busy_check, progress_callback, on_complete,
            )
        )
        self._polling_tasks[task_id] = task
        logger.info("启动后台轮询: platform=%s interval=%.1fs", platform, poll_interval)

    def stop_polling(self, task_id: str) -> None:
        """停止指定任务的轮询"""
        task = self._polling_tasks.pop(task_id, None)
        if task and not task.done():
            task.cancel()
            logger.info("停止后台轮询: task_id=%s", task_id)

    def stop_all(self) -> None:
        """停止所有轮询"""
        for task_id in list(self._polling_tasks.keys()):
            self.stop_polling(task_id)

    async def _poll_loop(
        self,
        task_id: str,
        platform: str,
        client: Any,
        poll_interval: float,
        max_polls: int,
        agent_busy_check: Callable[[], bool] | None,
        progress_callback: Callable[[str, int, bool, str | None], Awaitable[None]] | None,
        on_complete: Callable[[str], Awaitable[dict]] | None,
    ) -> None:
        """轮询循环：检查任务状态，完成时执行 on_complete 并入队通知"""
        polls = 0
        start = time.time()
        consecutive_errors = 0
        try:
            while polls < max_polls:
                polls += 1
                await asyncio.sleep(poll_interval)

                try:
                    result = await client.get_status(platform)
                except Exception as e:
                    logger.warning("轮询 %s 状态失败: %s", platform, e)
                    consecutive_errors += 1
                    if progress_callback:
                        try:
                            await progress_callback(platform, polls, True, f"连接失败({consecutive_errors}次)")
                        except Exception:
                            pass
                    continue

                if not result.get("success"):
                    error_msg = result.get("error", "未知错误")
                    logger.warning("轮询 %s 返回失败: %s", platform, error_msg)
                    consecutive_errors += 1
                    if progress_callback:
                        try:
                            await progress_callback(platform, polls, True, error_msg)
                        except Exception:
                            pass
                    continue

                consecutive_errors = 0
                data = result.get("data", {})
                is_running = data.get("isRunning", False)

                if progress_callback:
                    try:
                        await progress_callback(platform, polls, is_running, None)
                    except Exception as e:
                        logger.warning("进度回调失败: %s", e)

                if not is_running:
                    # 任务完成
                    elapsed = time.time() - start
                    sync_result = {}
                    if on_complete:
                        try:
                            sync_result = await on_complete(platform)
                            logger.info("%s on_complete 执行完成: %s", platform, sync_result)
                        except Exception as e:
                            logger.warning("%s on_complete 执行失败: %s", platform, e)

                    message = f"{platform} 平台获取任务已完成"
                    if sync_result:
                        inserted = sync_result.get("inserted", 0)
                        updated = sync_result.get("updated", 0)
                        total = sync_result.get("total_fetched", 0)
                        message += f"，已自动同步到本地（拉取 {total} 条，新增 {inserted}，更新 {updated}）"

                    notif = TaskNotification(
                        task_id=task_id,
                        platform=platform,
                        status="completed",
                        message=message,
                        data={"sync_result": sync_result},
                    )
                    self.enqueue(notif)

                    agent_busy = agent_busy_check() if agent_busy_check else False
                    if not agent_busy and self._ui_callback:
                        try:
                            await self._ui_callback(notif)
                        except Exception as e:
                            logger.warning("UI 推送失败: %s", e)

                    logger.info("%s 任务完成，已入队通知 (agent_busy=%s)", platform, agent_busy)
                    return

            # 超时
            elapsed = time.time() - start
            notif = TaskNotification(
                task_id=task_id,
                platform=platform,
                status="timeout",
                message=f"{platform} 任务轮询超时（已等待 {elapsed:.0f}s）",
            )
            self.enqueue(notif)
            logger.warning("%s 任务轮询超时", platform)

        except asyncio.CancelledError:
            logger.info("轮询被取消: task_id=%s", task_id)
        except Exception as e:
            logger.error("轮询异常: task_id=%s error=%s", task_id, e)
        finally:
            self._polling_tasks.pop(task_id, None)
