"""
岗位数据映射与入库 — 从 platform_sync.py 抽取的公共逻辑

供 tools/crawler/ 下的 Tool 复用。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 薪资解析
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"(\d+)\s*[Kk]?\s*[-–]\s*(\d+)\s*[Kk]")
_SINGLE_RE = re.compile(r"(\d+)\s*[Kk]")
_MONTHS_RE = re.compile(r"[·.](\d+)薪")


def parse_salary(text: str | None) -> tuple[int | None, int | None, int | None]:
    if not text:
        return None, None, None
    s = text.strip()
    if not s or "面议" in s:
        return None, None, None
    months: int | None = None
    mm = _MONTHS_RE.search(s)
    if mm:
        months = int(mm.group(1))
    cleaned = re.sub(r"[·.]?\d+薪", "", s)
    m = _RANGE_RE.search(cleaned)
    if m:
        return int(m.group(1)), int(m.group(2)), months
    m = _SINGLE_RE.search(cleaned)
    if m:
        v = int(m.group(1))
        return v, v, months
    return None, None, months


# ---------------------------------------------------------------------------
# 字段映射
# ---------------------------------------------------------------------------

def map_liepin(item: dict) -> dict:
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


async def upsert_jobs(db, rows: list[dict]) -> tuple[int, int]:
    """批量 upsert，返回 (inserted, updated)。"""
    inserted = 0
    updated = 0
    for row in rows:
        if not row.get("url"):
            continue
        existing = await db.execute("SELECT id FROM jobs WHERE url = ?", (row["url"],))
        values = (
            row["url"], row.get("title"), row.get("company"),
            row.get("salary_min"), row.get("salary_max"), row.get("salary_months"),
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
