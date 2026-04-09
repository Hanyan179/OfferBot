"""真实测试 GetjobClient 对接 getjob 服务"""
import asyncio
import sys

sys.path.insert(0, ".")
from services.getjob_client import GetjobClient


async def main():
    client = GetjobClient("http://localhost:8888")

    print("=== 1. 健康检查 ===")
    r = await client.health_check()
    print(f"  success={r['success']}, data={r.get('data')}")

    print("\n=== 2. 猎聘登录状态 ===")
    r = await client.login_status("liepin")
    print(f"  success={r['success']}, data={r.get('data')}")

    print("\n=== 3. 猎聘任务状态 ===")
    r = await client.get_status("liepin")
    print(f"  success={r['success']}, data={r.get('data')}")

    print("\n=== 4. 猎聘配置 ===")
    r = await client.get_config("liepin")
    if r["success"]:
        cfg = r["data"].get("config", {})
        print(f"  keywords={cfg.get('keywords')}")
        print(f"  city={cfg.get('city')}")
        print(f"  scrapeOnly={cfg.get('scrapeOnly')}")
    else:
        print(f"  FAIL: {r['error']}")

    print("\n=== 5. 猎聘岗位列表（前2条）===")
    r = await client.get_job_list("liepin", page=1, size=2)
    if r["success"]:
        data = r["data"]
        print(f"  total={data['total']}")
        for item in data.get("items", []):
            print(f"  - {item['jobTitle']} | {item['compName']} | {item['jobSalaryText']} | {item['jobArea']}")
    else:
        print(f"  FAIL: {r['error']}")

    print("\n=== 6. 猎聘统计 ===")
    r = await client.get_stats("liepin")
    if r["success"]:
        kpi = r["data"].get("kpi", {})
        print(f"  total={kpi.get('total')}, delivered={kpi.get('delivered')}, pending={kpi.get('pending')}")
    else:
        print(f"  FAIL: {r['error']}")

    print("\n=== 7. 无效平台 ===")
    r = await client.get_status("boss")
    err = r.get("error") or ""
    print(f"  success={r['success']}, error={err[:80]}")

    print("\n=== 8. 服务不可达 ===")
    bad = GetjobClient("http://localhost:9999")
    r = await bad.health_check()
    err = r.get("error") or ""
    print(f"  success={r['success']}, error={err[:80]}")
    await bad.close()

    await client.close()
    print("\n=== 全部测试完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
