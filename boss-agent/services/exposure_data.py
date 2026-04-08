"""Anthropic Economic Index — 确定性数据匹配。

数据链路：用户岗位(中文) → O*NET 代码 → job_exposure(职业曝光度) + task_penetration(任务渗透率)
"""

import csv
import json
from pathlib import Path

_DIR = Path(__file__).parent.parent / "data" / "economic_index"

# ---- 缓存 ----
_exposure: dict[str, dict] | None = None       # occ_code -> {title, exposure}
_task_pen: dict[str, float] | None = None       # task_text -> penetration
_occ_tasks: dict[str, list[str]] | None = None  # occ_code -> [task_text]
_mapping: dict[str, list[str]] | None = None    # 中文岗位名 -> [occ_code]
_titles_zh: dict[str, str] | None = None        # occ_code -> 中文职业名


def _load_titles_zh() -> dict[str, str]:
    global _titles_zh
    if _titles_zh is not None:
        return _titles_zh
    p = _DIR / "occ_titles_zh.json"
    _titles_zh = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _titles_zh


def _load_exposure() -> dict[str, dict]:
    global _exposure
    if _exposure is not None:
        return _exposure
    _exposure = {}
    with open(_DIR / "job_exposure.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            _exposure[r["occ_code"]] = {
                "title": r["title"],
                "exposure": float(r["observed_exposure"]),
            }
    return _exposure


def _load_task_penetration() -> dict[str, float]:
    global _task_pen
    if _task_pen is not None:
        return _task_pen
    _task_pen = {}
    with open(_DIR / "task_penetration.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            _task_pen[r["task"].strip().lower()] = float(r["penetration"])
    return _task_pen


def _load_occ_tasks() -> dict[str, list[str]]:
    global _occ_tasks
    if _occ_tasks is not None:
        return _occ_tasks
    _occ_tasks = {}
    with open(_DIR / "task_statements.txt", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            code = r["O*NET-SOC Code"].strip().replace(".00", "")
            task = r["Task"].strip()
            _occ_tasks.setdefault(code, []).append(task)
    return _occ_tasks


def _load_mapping() -> dict[str, list[str]]:
    """加载中文岗位 → O*NET 代码映射表（扁平化）。"""
    global _mapping
    if _mapping is not None:
        return _mapping
    _mapping = {}
    with open(_DIR / "occ_mapping.json", encoding="utf-8") as f:
        data = json.load(f)
    for category, jobs in data.items():
        if category == "_meta":
            continue
        if isinstance(jobs, dict):
            for job_name, codes in jobs.items():
                if isinstance(codes, list):
                    _mapping[job_name] = codes
    return _mapping


def match_occupation(user_role: str) -> list[dict]:
    """根据中文岗位名匹配 O*NET 职业，返回确定性数据。

    Returns: [{occ_code, title, exposure}]
    """
    mapping = _load_mapping()
    exposure = _load_exposure()

    # 精确匹配
    codes = mapping.get(user_role)
    if not codes:
        # 模糊匹配：包含关系
        user_lower = user_role.lower()
        for name, c in mapping.items():
            if name in user_role or user_role in name:
                codes = c
                break
    if not codes:
        # 关键词匹配
        for name, c in mapping.items():
            name_lower = name.lower()
            if any(kw in user_lower for kw in name_lower.split()) or any(kw in name_lower for kw in user_lower.split()):
                codes = c
                break
    if not codes:
        return []

    result = []
    seen = set()
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        info = exposure.get(code)
        if info:
            zh = _load_titles_zh().get(code, "")
            title_display = f"{zh}（{info['title']}）" if zh else info["title"]
            result.append({"occ_code": code, "title": info["title"], "title_zh": zh, "title_display": title_display, "exposure": info["exposure"]})
    return result


def get_task_details(occ_codes: list[str], top_high: int = 8, top_low: int = 5) -> dict:
    """获取指定职业的任务级渗透率数据。

    Returns: {
        "high_penetration": [{task, penetration}],  # AI 渗透率最高的任务
        "low_penetration": [{task, penetration}],    # AI 渗透率最低的任务（AI 难以替代）
        "total_tasks": int,
        "avg_penetration": float,
    }
    """
    occ_tasks = _load_occ_tasks()
    task_pen = _load_task_penetration()

    all_tasks = []
    for code in occ_codes:
        for task in occ_tasks.get(code, []):
            pen = task_pen.get(task.lower())
            if pen is None:
                pen = task_pen.get(task.lower().rstrip("."))
            if pen is not None:
                all_tasks.append({"task": task, "penetration": pen})

    if not all_tasks:
        return {"high_penetration": [], "low_penetration": [], "total_tasks": 0, "avg_penetration": 0}

    # 去重（多个职业可能共享任务）
    seen = set()
    unique = []
    for t in all_tasks:
        key = t["task"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)

    unique.sort(key=lambda x: -x["penetration"])
    avg = sum(t["penetration"] for t in unique) / len(unique) if unique else 0

    return {
        "high_penetration": unique[:top_high],
        "low_penetration": list(reversed(unique[-top_low:])),
        "total_tasks": len(unique),
        "avg_penetration": round(avg, 4),
    }
