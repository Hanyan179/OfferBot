"""
SyncJobsTool — 从 getjob 同步岗位数据到本地 jobs 表

支持猎聘和智联两个平台的字段映射、薪资解析、Upsert。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agent.tool_registry import Tool
from services.getjob_client import CONNECTION_REFUSED_MARKER

logger = logging.getLogger(__name__)

_SERVICE_DOWN_MSG = (
    "getjob 服务未启动，请先运行 getjob"
    "（cd reference-crawler && ./gradlew bootRun，端口 8888）"
)

VALID_PLATFORMS = ("liepin", "zhilian")

# ---------------------------------------------------------------------------
# 薪资解析
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"(\d+)\s*[Kk]?\s*[-–]\s*(\d+)\s*[Kk]")
_SINGLE_RE = re.compile(r"(\d+)\s*[Kk]")
_MONTHS_RE = re.compile(r"[·.](\d+)薪")


def parse_salary(text: str | None) -> tuple[int | None, int | None, int | None]:
    """
    解析薪资字符串为 (min_k, max_k, salary_months)。

    支持格式：
    - "25-50K" → (25, 50, None)
    - "25K-50K" → (25, 50, None)
    - "25-50K·14薪" → (25, 50, 14)
    - "面议" → (None, None, None)
    - "" → (None, None, None)
    """
    if not text:
        return None, None, None
    s = text.strip()
    if not s or "面议" in s:
        return None, None, None

    # 提取 ·N薪 后缀
    months: int | None = None
    mm = _MONTHS_RE.search(s)
    if mm:
        months = int(mm.group(1))

    # 去掉 ·N薪 后缀再解析数值
    cleaned = re.sub(r"[·.]?\d+薪", "", s)
    m = _RANGE_RE.search(cleaned)
    if m:
        return int(m.group(1)), int(m.group(2)), months
    m = _SINGLE_RE.search(cleaned)
    if m:
        v = int(m.group(1))
        return v, v, months
    return None, None, None


def format_salary(min_k: int, max_k: int) -> str:
    """格式化薪资数值为字符串（round-trip 用）。"""
    if min_k == max_k:
        return f"{min_k}K"
    return f"{min_k}-{max_k}K"


# ---------------------------------------------------------------------------
# 字段映射
# ---------------------------------------------------------------------------

def _map_liepin(item: dict) -> dict:
    """猎聘字段 → jobs 表字段。"""
    salary_text = item.get("jobSalaryText") or item.get("job_salary_text")
    s_min, s_max, s_months = parse_salary(salary_text)
    return {
        "url": item.get("jobLink") or item.get("job_link") or "",
        "title": item.get("jobTitle") or item.get("job_title") or "",
        "company": item.get("compName") or item.get("comp_name") or "",
        "salary_min": s_min,
        "salary_max": s_max,
        "salary_months": s_months,
        "city": item.get("jobArea") or item.get("job_area") or "",
        "experience": item.get("jobExpReq") or item.get("job_exp_req") or "",
        "education": item.get("jobEduReq") or item.get("job_edu_req") or "",
        "company_industry": item.get("compIndustry") or item.get("comp_industry") or "",
        "company_size": item.get("compScale") or item.get("comp_scale") or "",
        "recruiter_name": item.get("hrName") or item.get("hr_name") or "",
        "recruiter_title": item.get("hrTitle") or item.get("hr_title") or "",
        "platform": "liepin",
    }


def _map_zhilian(item: dict) -> dict:
    """智联字段 → jobs 表字段。"""
    salary_text = item.get("salary") or ""
    s_min, s_max, s_months = parse_salary(salary_text)
    return {
        "url": item.get("jobLink") or item.get("job_link") or "",
        "title": item.get("jobTitle") or item.get("job_title") or "",
        "company": item.get("companyName") or item.get("company_name") or "",
        "salary_min": s_min,
        "salary_max": s_max,
        "salary_months": s_months,
        "city": item.get("location") or "",
        "experience": item.get("experience") or "",
        "education": item.get("degree") or "",
        "platform": "zhilian",
    }


_MAPPERS = {"liepin": _map_liepin, "zhilian": _map_zhilian}


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT INTO jobs (url, title, company, salary_min, salary_max, salary_months, city,
                  experience, education, company_industry, company_size,
                  recruiter_name, recruiter_title, platform)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(url) DO UPDATE SET
    title = excluded.title,
    company = excluded.company,
    salary_min = excluded.salary_min,
    salary_max = excluded.salary_max,
    salary_months = excluded.salary_months,
    city = excluded.city,
    experience = excluded.experience,
    education = excluded.education,
    company_industry = excluded.company_industry,
    company_size = excluded.company_size,
    recruiter_name = excluded.recruiter_name,
    recruiter_title = excluded.recruiter_title,
    updated_at = CURRENT_TIMESTAMP
"""


async def _upsert_jobs(db, rows: list[dict]) -> tuple[int, int]:
    """批量 upsert，返回 (inserted, updated)。"""
    inserted = 0
    updated = 0
    for row in rows:
        if not row.get("url"):
            continue
        # 检查是否已存在
        existing = await db.execute(
            "SELECT id FROM jobs WHERE url = ?", (row["url"],)
        )
        values = (
            row["url"], row.get("title"), row.get("company"),
            row.get("salary_min"), row.get("salary_max"),
            row.get("salary_months"),
            row.get("city"), row.get("experience"), row.get("education"),
            row.get("company_industry", ""), row.get("company_size", ""),
            row.get("recruiter_name", ""), row.get("recruiter_title", ""),
            row["platform"],
        )
        await db.execute_write(_UPSERT_SQL, values)
        if existing:
            updated += 1
        else:
            inserted += 1
    return inserted, updated


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class SyncJobsTool(Tool):
    @property
    def name(self) -> str:
        return "sync_jobs"

    @property
    def toolset(self) -> str:
        return "crawl"

    @property
    def toolset(self) -> str:
        return "crawl"

    @property
    def display_name(self) -> str:
        return "同步岗位数据"

    @property
    def description(self) -> str:
        return (
            "从 getjob 服务同步岗位数据到本地 jobs 表。"
            "支持猎聘和智联，逐页拉取并 upsert。"
        )

    @property
    def category(self) -> str:
        return "getjob"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["liepin", "zhilian"], "description": "平台名称"},
                "page_size": {"type": "integer", "description": "每页拉取数量", "default": 50},
                "max_pages": {"type": "integer", "description": "最大拉取页数", "default": 20},
            },
            "required": ["platform"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        platform = params.get("platform", "")
        if platform not in VALID_PLATFORMS:
            return {"success": False, "error": f"不支持的平台: {platform}，请使用 liepin 或 zhilian"}

        client = context["getjob_client"]
        db = context["db"]
        mapper = _MAPPERS[platform]
        page_size = params.get("page_size", 50)
        max_pages = params.get("max_pages", 20)

        total_fetched = 0
        total_inserted = 0
        total_updated = 0

        for page_num in range(1, max_pages + 1):
            result = await client.get_job_list(platform, page=page_num, size=page_size)
            if not result["success"]:
                if result.get("error") and CONNECTION_REFUSED_MARKER in result["error"]:
                    return {"success": False, "error": _SERVICE_DOWN_MSG}
                if total_fetched == 0:
                    return result
                break  # 已有部分数据，停止拉取

            data = result.get("data", {})
            items = data.get("items", [])
            if not items:
                break

            rows = [mapper(item) for item in items]
            inserted, updated = await _upsert_jobs(db, rows)
            total_fetched += len(items)
            total_inserted += inserted
            total_updated += updated

            # 如果返回的数据少于 page_size，说明已到最后一页
            total = data.get("total", 0)
            if len(items) < page_size or total_fetched >= total:
                break

        return {
            "success": True,
            "data": {
                "platform": platform,
                "total_fetched": total_fetched,
                "inserted": total_inserted,
                "updated": total_updated,
            },
        }
