"""
模拟 AI Agent 完整流程测试

1. Agent 自动启动 getjob 服务
2. 等待用户登录（这里跳过，假设已登录）
3. 根据用户画像配置搜索条件
4. 启动 scrapeOnly 爬取
5. 等待完成
6. 同步数据到本地
7. 展示推荐岗位（带链接）
"""
import asyncio
import sys
import time

sys.path.insert(0, ".")

from services.getjob_client import GetjobClient
from tools.getjob.service_manager import GetjobServiceManagerTool
from tools.getjob.platform_sync import _map_liepin, _upsert_jobs
from db.database import Database
from config import load_config


async def main():
    config = load_config()
    client = GetjobClient(config.getjob_base_url)
    db = Database(config.db_path)
    await db.connect()
    await db.init_schema()

    context = {"getjob_client": client, "db": db}

    print("=" * 60)
    print("  AI Agent 完整流程测试")
    print("=" * 60)

    # --- Step 1: 检查/启动 getjob 服务 ---
    print("\n[Agent] 检查 getjob 服务...")
    svc_tool = GetjobServiceManagerTool()
    r = await svc_tool.execute({"action": "check"}, context)
    if r.get("running"):
        print("  getjob 已在运行")
    else:
        print("  getjob 未运行，正在自动启动...")
        r = await svc_tool.execute({"action": "start"}, context)
        if r["success"]:
            print(f"  {r['message']}")
        else:
            print(f"  启动失败: {r['error']}")
            return

    # --- Step 2: 检查登录 ---
    print("\n[Agent] 检查猎聘登录状态...")
    r = await client.login_status("liepin")
    if not r["success"]:
        print(f"  查询失败: {r['error']}")
        return
    if not r["data"].get("isLoggedIn"):
        print("  未登录！请在浏览器中扫码登录猎聘...")
        print("  (等待 30 秒让你登录)")
        await asyncio.sleep(30)
        r = await client.login_status("liepin")
        if not r["data"].get("isLoggedIn"):
            print("  仍未登录，退出")
            return
    print("  已登录")

    # --- Step 3: 模拟从用户画像提取搜索条件 ---
    print("\n[Agent] 从用户画像提取搜索条件...")
    # 模拟用户画像
    user_keywords = '["AI工程师","Python后端"]'
    user_city = "上海"
    user_salary = "20$50"
    print(f"  关键词: {user_keywords}")
    print(f"  城市: {user_city}")
    print(f"  薪资: {user_salary}")

    # --- Step 4: 配置并启动 scrapeOnly 爬取 ---
    print("\n[Agent] 配置 scrapeOnly 爬取...")
    r = await client.update_config("liepin", {
        "scrapeOnly": True,
        "keywords": user_keywords,
        "city": user_city,
        "salaryCode": user_salary,
    })
    if not r["success"]:
        print(f"  配置失败: {r['error']}")
        return
    print(f"  配置成功: scrapeOnly={r['data'].get('scrapeOnly')}")

    print("\n[Agent] 启动爬取任务...")
    r = await client.start_task("liepin")
    if not r["success"]:
        print(f"  启动失败: {r['error']}")
        return
    print("  任务已启动")

    # --- Step 5: 等待完成（最多 2 分钟）---
    print("\n[Agent] 等待爬取完成...")
    start = time.time()
    while time.time() - start < 120:
        await asyncio.sleep(5)
        r = await client.get_status("liepin")
        sr = await client.get_stats("liepin")
        total = sr["data"].get("kpi", {}).get("total", 0) if sr["success"] else 0
        running = r["data"].get("isRunning", False) if r["success"] else False
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] running={running}, 已爬取={total}")
        if not running:
            break

    # --- Step 6: 同步到本地 ---
    print("\n[Agent] 同步数据到本地...")
    total_synced = 0
    page = 1
    while True:
        r = await client.get_job_list("liepin", page=page, size=50)
        if not r["success"] or not r["data"].get("items"):
            break
        items = r["data"]["items"]
        rows = [_map_liepin(item) for item in items]
        ins, upd = await _upsert_jobs(db, rows)
        total_synced += len(items)
        if len(items) < 50:
            break
        page += 1
    print(f"  同步完成: {total_synced} 条")

    # --- Step 7: 展示推荐岗位（带链接）---
    print("\n[Agent] 为你推荐以下岗位：")
    print("-" * 60)
    rows = await db.execute(
        "SELECT url, title, company, salary_min, salary_max, city "
        "FROM jobs WHERE platform = 'liepin' AND salary_min >= 20 "
        "ORDER BY salary_max DESC LIMIT 10"
    )
    for i, r in enumerate(rows, 1):
        sal = f"{r['salary_min']}-{r['salary_max']}K" if r['salary_min'] else "面议"
        print(f"  {i}. {r['title']} | {r['company']} | {sal} | {r['city']}")
        print(f"     链接: {r['url']}")
    print("-" * 60)

    await client.close()
    print("\n测试完成")


if __name__ == "__main__":
    asyncio.run(main())
