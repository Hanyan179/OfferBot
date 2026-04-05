"""
端到端爬取测试 — 模拟 AI Agent 的完整流程

1. 检查 getjob 服务健康
2. 检查猎聘登录状态
3. 配置 scrapeOnly=true + 搜索条件
4. 启动爬取任务
5. 轮询等待任务完成
6. 同步数据到本地 jobs 表
7. 验证本地数据
"""
import asyncio
import sys
import time

sys.path.insert(0, ".")

from services.getjob_client import GetjobClient
from tools.getjob.platform_sync import parse_salary, _map_liepin, _upsert_jobs
from db.database import Database
from config import load_config


async def main():
    config = load_config()
    client = GetjobClient(config.getjob_base_url)
    db = Database(config.db_path)
    await db.connect()
    await db.init_schema()

    print("=" * 60)
    print("  猎聘爬取端到端测试")
    print("=" * 60)

    # --- Step 1: 健康检查 ---
    print("\n[Step 1] 检查 getjob 服务...")
    r = await client.health_check()
    if not r["success"]:
        print(f"  FAIL: {r['error']}")
        print("  请先启动 getjob: cd reference-crawler && ./gradlew bootRun")
        return
    print(f"  OK: {r['data']}")

    # --- Step 2: 登录状态 ---
    print("\n[Step 2] 检查猎聘登录状态...")
    r = await client.login_status("liepin")
    if not r["success"]:
        print(f"  FAIL: {r['error']}")
        return
    logged_in = r["data"].get("isLoggedIn", False)
    if not logged_in:
        print("  未登录！请在浏览器中扫码登录猎聘")
        return
    print("  OK: 已登录")

    # --- Step 3: 配置 scrapeOnly ---
    print("\n[Step 3] 配置搜索条件 (scrapeOnly=true)...")
    r = await client.update_config("liepin", {
        "scrapeOnly": True,
        "keywords": '["Python"]',
        "city": "上海",
        "salaryCode": "15$30",
    })
    if not r["success"]:
        print(f"  FAIL: {r['error']}")
        return
    cfg = r["data"]
    print(f"  OK: keywords={cfg.get('keywords')}, city={cfg.get('city')}, scrapeOnly={cfg.get('scrapeOnly')}")

    # --- Step 4: 启动爬取 ---
    print("\n[Step 4] 启动爬取任务...")
    r = await client.start_task("liepin")
    if not r["success"]:
        data = r.get("data") or {}
        if isinstance(data, dict) and data.get("status") == "running":
            print("  任务已在运行中，等待完成...")
        else:
            print(f"  FAIL: {r['error']}")
            return
    else:
        print(f"  OK: {r['data'].get('message', 'started')}")

    # --- Step 5: 轮询等待完成 ---
    print("\n[Step 5] 等待爬取完成...")
    max_wait = 180  # 最多等 3 分钟
    start = time.time()
    last_total = 0
    while time.time() - start < max_wait:
        await asyncio.sleep(5)
        r = await client.get_status("liepin")
        if not r["success"]:
            print(f"  状态查询失败: {r['error']}")
            break
        is_running = r["data"].get("isRunning", False)

        # 查统计
        sr = await client.get_stats("liepin")
        total = 0
        if sr["success"]:
            total = sr["data"].get("kpi", {}).get("total", 0)

        elapsed = int(time.time() - start)
        if total != last_total:
            print(f"  [{elapsed}s] running={is_running}, total={total}")
            last_total = total

        if not is_running:
            print(f"  任务完成！耗时 {elapsed}s，共爬取 {total} 条")
            break
    else:
        print(f"  超时！已等待 {max_wait}s")
        # 停止任务
        await client.stop_task("liepin")

    # --- Step 6: 拉取数据并同步到本地 ---
    print("\n[Step 6] 同步数据到本地 jobs 表...")
    total_fetched = 0
    total_inserted = 0
    total_updated = 0
    page = 1
    while True:
        r = await client.get_job_list("liepin", page=page, size=50)
        if not r["success"]:
            print(f"  拉取第 {page} 页失败: {r['error']}")
            break
        items = r["data"].get("items", [])
        if not items:
            break

        rows = [_map_liepin(item) for item in items]
        inserted, updated = await _upsert_jobs(db, rows)
        total_fetched += len(items)
        total_inserted += inserted
        total_updated += updated
        print(f"  第 {page} 页: {len(items)} 条, 新增 {inserted}, 更新 {updated}")

        if len(items) < 50:
            break
        page += 1

    print(f"  同步完成: 拉取 {total_fetched} 条, 新增 {total_inserted}, 更新 {total_updated}")

    # --- Step 7: 验证本地数据 ---
    print("\n[Step 7] 验证本地 jobs 表数据...")
    rows = await db.execute(
        "SELECT COUNT(*) as cnt FROM jobs WHERE platform = 'liepin'"
    )
    local_count = rows[0]["cnt"]
    print(f"  本地 liepin 岗位数: {local_count}")

    # 抽样检查
    samples = await db.execute(
        "SELECT url, title, company, salary_min, salary_max, city, platform "
        "FROM jobs WHERE platform = 'liepin' ORDER BY id DESC LIMIT 3"
    )
    for s in samples:
        print(f"  - {s['title']} | {s['company']} | {s['salary_min']}-{s['salary_max']}K | {s['city']}")

    # 检查薪资解析
    null_salary = await db.execute(
        "SELECT COUNT(*) as cnt FROM jobs WHERE platform = 'liepin' AND salary_min IS NULL"
    )
    print(f"  薪资为空的岗位数: {null_salary[0]['cnt']} (面议或解析失败)")

    print("\n" + "=" * 60)
    print("  测试完成")
    print("=" * 60)

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
