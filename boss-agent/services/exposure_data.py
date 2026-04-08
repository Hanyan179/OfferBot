"""Anthropic Economic Index — job_exposure 数据加载与匹配。"""

import csv
from pathlib import Path
from difflib import SequenceMatcher

_DATA_PATH = Path(__file__).parent.parent / "data" / "economic_index" / "job_exposure.csv"

_cache: list[dict] | None = None


def _load() -> list[dict]:
    global _cache
    if _cache is not None:
        return _cache
    rows = []
    with open(_DATA_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "occ_code": r["occ_code"],
                "title": r["title"],
                "exposure": float(r["observed_exposure"]),
            })
    _cache = rows
    return _cache


def search(query: str, top_k: int = 5) -> list[dict]:
    """按职业名称模糊匹配，返回最相关的 top_k 条。"""
    data = _load()
    q = query.lower()
    scored = []
    for row in data:
        t = row["title"].lower()
        # 完全包含优先
        if q in t or t in q:
            s = 0.9 + SequenceMatcher(None, q, t).ratio() * 0.1
        else:
            s = SequenceMatcher(None, q, t).ratio()
        scored.append((s, row))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:top_k]]


def get_all() -> list[dict]:
    """返回全部 756 条职业数据。"""
    return _load()
