"""
getjob 数据流真实集成测试

直接用真实数据库 + getjob 服务验证以下场景：
1. 场景 A：对已有 JD 的岗位调用 fetch_detail → 应走缓存，skipped=N
2. 场景 B：对缺 JD 的岗位调用 fetch_detail → 应远程爬取
3. 场景 C：混合批次（有 JD + 缺 JD）→ 验证 skipped + fetched 计数
4. 场景 D：force=true 对已有 JD 的岗位 → 应强制重新爬取
5. 场景 E：query_jobs jd_status="stats" → 验证覆盖率统计
6. 场景 F：query_jobs jd_status="has_jd" / "missing_jd" → 验证过滤
7. 场景 G：query_jobs 普通查询 → 验证 has_jd 字段存在

用法：
    cd boss-agent && python3 scripts/test_getjob_dataflow_live.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# 确保 boss-agent 在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from db.database import Database
from services.getjob_client import GetjobClient
from tools.data.query_jobs import QueryJobsTool
from tools.getjob.fetch_detail import FetchJobDetailTool


def pp(label: str, data: dict) -> None:
    """Pretty print result."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    # 对 results 列表截断 jd_preview 避免刷屏
    if "results" in data:
        for r in data["results"]:
            if r.get("jd_preview"):
                r["jd_preview"] = r["jd_preview"][:80] + "..."
    if "jobs" in data:
        shown = data.copy()
        shown["jobs"] = f"[{len(data['jobs'])} 条, 省略]"
        print(json.dumps(shown, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))



async def main() -> None:
    cfg = load_config()
    db = Database(cfg.db_path)
    await db.connect()
    client = GetjobClient(cfg.getjob_base_url)

    fetch_tool = FetchJobDetailTool()
    query_tool = QueryJobsTool()

    ctx = {"db": db, "getjob_client": client}
    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✅ {name}")
        else:
            failed += 1
            print(f"  ❌ {name} — {detail}")

    # ------------------------------------------------------------------
    # 准备：找出有 JD 和缺 JD 的岗位 ID
    # ------------------------------------------------------------------
    has_jd_rows = await db.execute(
        "SELECT id, title FROM jobs WHERE raw_jd IS NOT NULL AND raw_jd != '' LIMIT 3"
    )
    missing_jd_rows = await db.execute(
        "SELECT id, title, url FROM jobs WHERE (raw_jd IS NULL OR raw_jd = '') AND url IS NOT NULL AND url != '' AND url != '#' LIMIT 2"
    )

    has_jd_ids = [r["id"] for r in has_jd_rows]
    missing_jd_ids = [r["id"] for r in missing_jd_rows]

    print("\n准备数据:")
    print(f"  有 JD 的岗位 IDs: {has_jd_ids}")
    print(f"  缺 JD 的岗位 IDs: {missing_jd_ids}")

    # ==================================================================
    # 场景 A：已有 JD 的岗位 → 应走缓存
    # ==================================================================
    result_a = await fetch_tool.execute({"job_ids": has_jd_ids}, ctx)
    pp("场景 A: 已有 JD → 走缓存", result_a)

    check("A.1 success=True", result_a["success"])
    check("A.2 skipped == 有JD数", result_a["skipped"] == len(has_jd_ids),
          f"skipped={result_a['skipped']}, expected={len(has_jd_ids)}")
    check("A.3 fetched == 0", result_a["fetched"] == 0,
          f"fetched={result_a['fetched']}")
    for r in result_a.get("results", []):
        check(f"A.4 source=local_cache (id={r['id']})", r.get("source") == "local_cache",
              f"source={r.get('source')}")
        check(f"A.5 有 jd_length (id={r['id']})", "jd_length" in r and r["jd_length"] > 0,
              f"jd_length={r.get('jd_length')}")

    # ==================================================================
    # 场景 B：缺 JD 的岗位 → 远程爬取（需要 getjob 服务在线）
    # ==================================================================
    # 先检查 getjob 服务是否可用
    health = await client.health_check()
    getjob_online = health.get("success", False)
    print(f"\ngetjob 服务状态: {'在线 ✅' if getjob_online else '离线 ⚠️'}")

    if getjob_online and missing_jd_ids:
        # 只取 1 个来测试，避免大量爬取
        test_id = missing_jd_ids[0]
        result_b = await fetch_tool.execute({"job_ids": [test_id]}, ctx)
        pp("场景 B: 缺 JD → 远程爬取", result_b)

        check("B.1 skipped == 0", result_b["skipped"] == 0,
              f"skipped={result_b['skipped']}")
        if result_b["fetched"] > 0:
            check("B.2 fetched == 1", result_b["fetched"] == 1)
            r = result_b["results"][0]
            check("B.3 source=remote", r.get("source") == "remote",
                  f"source={r.get('source')}")
            check("B.4 有 jd_length", "jd_length" in r and r["jd_length"] > 0)

            # 验证 DB 里确实写入了
            db_check = await db.execute(
                "SELECT raw_jd FROM jobs WHERE id = ?", (test_id,)
            )
            check("B.5 DB 已写入 raw_jd", bool(db_check and db_check[0]["raw_jd"]))
        else:
            print("  ⚠️ 爬取未成功（可能是网络或页面问题），跳过 B.2-B.5")
    else:
        print("\n  ⚠️ getjob 服务离线或无缺 JD 岗位，跳过场景 B")

    # ==================================================================
    # 场景 C：混合批次（有 JD + 缺 JD）
    # ==================================================================
    if getjob_online and has_jd_ids and missing_jd_ids:
        # 用 1 个有 JD + 1 个缺 JD
        mix_ids = [has_jd_ids[0], missing_jd_ids[-1]]
        result_c = await fetch_tool.execute({"job_ids": mix_ids}, ctx)
        pp("场景 C: 混合批次", result_c)

        check("C.1 total == 2", result_c["total"] == 2,
              f"total={result_c['total']}")
        check("C.2 skipped >= 1", result_c["skipped"] >= 1,
              f"skipped={result_c['skipped']}")
        check("C.3 skipped + fetched + failed == total",
              result_c["skipped"] + result_c["fetched"] + result_c["failed"] == result_c["total"],
              f"{result_c['skipped']}+{result_c['fetched']}+{result_c['failed']} != {result_c['total']}")
    else:
        print("\n  ⚠️ 跳过场景 C（需要 getjob 在线 + 混合数据）")

    # ==================================================================
    # 场景 D：force=true → 强制重新爬取已有 JD 的岗位
    # ==================================================================
    if getjob_online and has_jd_ids:
        test_force_id = has_jd_ids[0]
        # 先记录原始 JD
        orig = await db.execute("SELECT raw_jd FROM jobs WHERE id = ?", (test_force_id,))
        orig_jd = orig[0]["raw_jd"] if orig else ""

        result_d = await fetch_tool.execute(
            {"job_ids": [test_force_id], "force": True}, ctx
        )
        pp("场景 D: force=true 强制爬取", result_d)

        check("D.1 skipped == 0", result_d["skipped"] == 0,
              f"skipped={result_d['skipped']}")
        if result_d["fetched"] > 0:
            check("D.2 source=remote", result_d["results"][0].get("source") == "remote")
        else:
            print("  ⚠️ force 爬取未成功，可能是网络问题")
    else:
        print("\n  ⚠️ 跳过场景 D（需要 getjob 在线）")

    # ==================================================================
    # 场景 E：query_jobs jd_status="stats"
    # ==================================================================
    result_e = await query_tool.execute({"jd_status": "stats"}, ctx)
    pp("场景 E: JD 覆盖率统计", result_e)

    check("E.1 success=True", result_e["success"])
    cov = result_e.get("jd_coverage", {})
    check("E.2 有 total 字段", "total" in cov, f"keys={list(cov.keys())}")
    check("E.3 有 has_jd 字段", "has_jd" in cov)
    check("E.4 有 missing_jd 字段", "missing_jd" in cov)
    if all(k in cov for k in ("total", "has_jd", "missing_jd")):
        check("E.5 total == has_jd + missing_jd",
              cov["total"] == cov["has_jd"] + cov["missing_jd"],
              f"{cov['total']} != {cov['has_jd']} + {cov['missing_jd']}")

    # ==================================================================
    # 场景 F：query_jobs jd_status 过滤
    # ==================================================================
    result_f1 = await query_tool.execute({"jd_status": "has_jd", "limit": 50}, ctx)
    pp("场景 F1: jd_status=has_jd", result_f1)
    check("F1.1 所有结果 has_jd=1",
          all(j.get("has_jd") == 1 for j in result_f1.get("jobs", [])),
          "存在 has_jd != 1 的记录")

    result_f2 = await query_tool.execute({"jd_status": "missing_jd", "limit": 5}, ctx)
    pp("场景 F2: jd_status=missing_jd", result_f2)
    check("F2.1 所有结果 has_jd=0",
          all(j.get("has_jd") == 0 for j in result_f2.get("jobs", [])),
          "存在 has_jd != 0 的记录")

    # ==================================================================
    # 场景 G：普通查询包含 has_jd 字段
    # ==================================================================
    result_g = await query_tool.execute({"limit": 5}, ctx)
    pp("场景 G: 普通查询含 has_jd", result_g)
    if result_g.get("jobs"):
        check("G.1 结果包含 has_jd 字段",
              "has_jd" in result_g["jobs"][0],
              f"字段列表: {list(result_g['jobs'][0].keys())}")
        check("G.2 has_jd 值为 0 或 1",
              all(j["has_jd"] in (0, 1) for j in result_g["jobs"]))

    # ------------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"  测试结果: {passed} 通过, {failed} 失败")
    print(f"{'='*60}\n")

    await client.close()
    await db.close()

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    asyncio.run(main())
