"""Anthropic Economic Index — 确定性数据匹配。

数据链路：用户岗位(中文) → O*NET 代码 → job_exposure(职业替代率) + task_penetration(任务渗透率)
"""

import csv
import json
from pathlib import Path

_DIR = Path(__file__).parent.parent / "data" / "economic_index"
_TASK_CN_PATH = _DIR / "task_translations.json"

# ---- 缓存 ----
_exposure: dict[str, dict] | None = None       # occ_code -> {title, exposure}
_task_pen: dict[str, float] | None = None       # task_text -> penetration
_occ_tasks: dict[str, list[str]] | None = None  # occ_code -> [task_text]
_mapping: dict[str, list[str]] | None = None    # 中文岗位名 -> [occ_code]
_task_cn: dict[str, str] | None = None          # english task -> chinese task


def _load_task_cn() -> dict[str, str]:
    global _task_cn
    if _task_cn is not None:
        return _task_cn
    if _TASK_CN_PATH.exists():
        _task_cn = json.loads(_TASK_CN_PATH.read_text(encoding="utf-8"))
    else:
        _task_cn = {}
    return _task_cn


def _save_task_cn():
    if _task_cn is not None:
        _TASK_CN_PATH.write_text(json.dumps(_task_cn, ensure_ascii=False, indent=2), encoding="utf-8")


async def translate_tasks(tasks: list[dict], api_key: str, base_url: str, model: str) -> list[dict]:
    """翻译任务列表，有缓存直接用，没有的批量调 LLM 翻译后缓存。"""
    cn_cache = _load_task_cn()
    to_translate = [t["task"] for t in tasks if t["task"] not in cn_cache]

    if to_translate:
        from openai import AsyncOpenAI
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(to_translate))
        prompt = f"将以下英文职业任务描述翻译为简洁的中文，每行一条，只输出翻译结果，保持编号：\n\n{numbered}"
        try:
            client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=30)
            resp = await client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], temperature=0,
            )
            lines = [l.strip() for l in resp.choices[0].message.content.strip().split("\n") if l.strip()]
            for i, en in enumerate(to_translate):
                if i < len(lines):
                    # 去掉编号前缀
                    cn = lines[i].lstrip("0123456789.、) ").strip()
                    cn_cache[en] = cn
            _save_task_cn()
        except Exception:
            pass  # 翻译失败就用英文

    return [{"task": cn_cache.get(t["task"], t["task"]), "penetration": t["penetration"]} for t in tasks]


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
    cn = _load_task_cn()
    _task_pen = {}
    with open(_DIR / "task_penetration.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            task_en = r["task"].strip()
            task = cn.get(task_en, task_en)
            _task_pen[task.lower()] = float(r["penetration"])
    return _task_pen


def _load_occ_tasks() -> dict[str, list[str]]:
    global _occ_tasks
    if _occ_tasks is not None:
        return _occ_tasks
    cn = _load_task_cn()
    _occ_tasks = {}
    with open(_DIR / "task_statements.txt", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            code = r["O*NET-SOC Code"].strip().replace(".00", "")
            task_en = r["Task"].strip()
            task = cn.get(task_en, task_en)
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
            result.append({"occ_code": code, "title": info["title"], "exposure": info["exposure"]})
    return result


def get_task_details(occ_codes: list[str], top_high: int = 8, top_low: int = 5) -> dict:
    """获取指定职业的任务级渗透率数据。"""
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
