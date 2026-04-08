"""
面试追踪和状态机工具

UpdateInterviewStatusTool: 更新岗位面试状态（含状态机校验）
GetInterviewFunnelTool: 获取面试漏斗转化率数据
辅助函数: get_interview_status, get_stage_history
"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool
from db.database import Database

# ---------------------------------------------------------------------------
# 面试状态机：合法状态转换路径
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, set[str]] = {
    "applied": {"viewed", "rejected", "withdrawn"},
    "viewed": {"replied", "rejected", "withdrawn"},
    "replied": {"interview_scheduled", "rejected", "withdrawn"},
    "interview_scheduled": {"round_1", "rejected", "withdrawn"},
    "round_1": {"round_2", "rejected", "withdrawn"},
    "round_2": {"round_3", "hr_round", "rejected", "withdrawn"},
    "round_3": {"hr_round", "rejected", "withdrawn"},
    "hr_round": {"offer", "rejected", "withdrawn"},
    "offer": set(),
    "rejected": set(),
    "withdrawn": set(),
}

ALL_STAGES = set(VALID_TRANSITIONS.keys())

# 漏斗阶段顺序（用于转化率计算）
FUNNEL_STAGES = [
    "applied", "viewed", "replied", "interview_scheduled",
    "round_1", "round_2", "round_3", "hr_round", "offer",
]


class UpdateInterviewStatusTool(Tool):
    """更新岗位面试状态，含状态机校验。"""

    @property
    def name(self) -> str:
        return "update_interview_status"

    @property
    def display_name(self) -> str:
        return "更新面试状态"

    @property
    def description(self) -> str:
        return "更新岗位面试状态"

    @property
    def category(self) -> str:
        return "data"

    @property
    def is_concurrency_safe(self) -> bool:
        return False

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "application_id": {
                    "type": "integer",
                    "description": "投递记录 ID",
                },
                "new_stage": {
                    "type": "string",
                    "description": "目标面试阶段",
                },
                "notes": {
                    "type": "string",
                    "description": "备注信息",
                },
                "interview_time": {
                    "type": "string",
                    "description": "面试时间（ISO 格式）",
                },
            },
            "required": ["application_id", "new_stage"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        """
        更新面试状态。

        1. 获取当前阶段（无记录则为 "applied"）
        2. 校验状态转换合法性
        3. 插入或更新 interview_tracking 记录
        4. 写入 interview_stage_log
        """
        db: Database = context["db"]

        application_id = params["application_id"]
        new_stage = params["new_stage"]
        notes = params.get("notes")
        interview_time = params.get("interview_time")

        # 1. 获取当前阶段
        current = await get_interview_status(db, application_id)
        from_stage = current["stage"] if current else "applied"

        # 2. 校验状态转换
        valid_targets = VALID_TRANSITIONS.get(from_stage, set())
        if new_stage not in valid_targets:
            return {
                "success": False,
                "error": f"非法状态转换: {from_stage} → {new_stage}",
            }

        # 3. 插入或更新 interview_tracking
        if current is None:
            await db.execute_write(
                "INSERT INTO interview_tracking "
                "(application_id, stage, stage_changed_at, notes, interview_time) "
                "VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)",
                (application_id, new_stage, notes, interview_time),
            )
        else:
            await db.execute_write(
                "UPDATE interview_tracking "
                "SET stage = ?, stage_changed_at = CURRENT_TIMESTAMP, "
                "notes = ?, interview_time = ? "
                "WHERE application_id = ?",
                (new_stage, notes, interview_time, application_id),
            )

        # 4. 写入 interview_stage_log
        await db.execute_write(
            "INSERT INTO interview_stage_log "
            "(application_id, from_stage, to_stage, changed_at, notes) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)",
            (application_id, from_stage, new_stage, notes),
        )

        return {
            "success": True,
            "from_stage": from_stage,
            "to_stage": new_stage,
        }


class GetInterviewFunnelTool(Tool):
    """获取面试漏斗转化率数据。"""

    @property
    def name(self) -> str:
        return "get_interview_funnel"

    @property
    def display_name(self) -> str:
        return "面试漏斗统计"

    @property
    def description(self) -> str:
        return "获取面试漏斗转化率数据"

    @property
    def category(self) -> str:
        return "data"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {},
        }

    async def execute(self, params: dict, context: Any) -> dict:
        """
        计算面试漏斗转化率。

        1. 统计总投递数（applications 表）
        2. 统计到达各阶段的投递数（interview_stage_log 中 to_stage 去重计数）
        3. 计算关键转化率
        """
        db: Database = context["db"]

        # 总投递数
        rows = await db.execute("SELECT COUNT(*) AS cnt FROM applications")
        total_applied = rows[0]["cnt"]

        # 统计到达各阶段的不同 application_id 数量
        stage_counts: dict[str, int] = {}
        for stage in FUNNEL_STAGES:
            if stage == "applied":
                stage_counts[stage] = total_applied
                continue
            rows = await db.execute(
                "SELECT COUNT(DISTINCT application_id) AS cnt "
                "FROM interview_stage_log WHERE to_stage = ?",
                (stage,),
            )
            stage_counts[stage] = rows[0]["cnt"]

        # 也统计 rejected 和 withdrawn
        for stage in ("rejected", "withdrawn"):
            rows = await db.execute(
                "SELECT COUNT(DISTINCT application_id) AS cnt "
                "FROM interview_stage_log WHERE to_stage = ?",
                (stage,),
            )
            stage_counts[stage] = rows[0]["cnt"]

        # 计算转化率（分母为 0 时返回 0.0）
        def rate(numerator_stage: str, denominator_stage: str) -> float:
            denom = stage_counts.get(denominator_stage, 0)
            if denom == 0:
                return 0.0
            return stage_counts.get(numerator_stage, 0) / denom

        funnel_data = {
            "total_applied": total_applied,
            "viewed_rate": rate("viewed", "applied"),
            "replied_rate": rate("replied", "viewed"),
            "interview_rate": rate("interview_scheduled", "replied"),
            "offer_rate": rate("offer", "interview_scheduled"),
            "stage_counts": stage_counts,
        }

        # 构建漏斗可视化数据
        funnel_stages = []
        for stage in FUNNEL_STAGES:
            funnel_stages.append({"stage": stage, "count": stage_counts.get(stage, 0)})

        # 面试列表（最近的面试记录）
        interviews = await db.execute(
            "SELECT a.id, j.title, j.company, it.current_stage, it.updated_at "
            "FROM interview_tracking it "
            "JOIN applications a ON it.application_id = a.id "
            "JOIN jobs j ON a.job_id = j.id "
            "ORDER BY it.updated_at DESC LIMIT 20"
        )

        return {
            "for_ui": {
                "element_name": "InterviewTracker",
                "funnel": funnel_stages,
                "interviews": [dict(r) for r in interviews],
            },
            "for_agent": funnel_data,
        }


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def get_interview_status(db: Database, application_id: int) -> dict | None:
    """获取当前面试追踪记录。"""
    rows = await db.execute(
        "SELECT * FROM interview_tracking WHERE application_id = ?",
        (application_id,),
    )
    return rows[0] if rows else None


async def get_stage_history(db: Database, application_id: int) -> list[dict]:
    """获取面试状态变更历史（按时间升序）。"""
    return await db.execute(
        "SELECT * FROM interview_stage_log "
        "WHERE application_id = ? ORDER BY id",
        (application_id,),
    )
