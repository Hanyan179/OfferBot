#!/usr/bin/env python3
"""
端到端测试：LiepinBrowser 真实爬取验证

用法：
    cd boss-agent
    python3 scripts/test_browser.py search --keyword "AI" --max-pages 1
    python3 scripts/test_browser.py detail --url "https://www.liepin.com/job/xxx"
    python3 scripts/test_browser.py login
    python3 scripts/test_browser.py all    # 搜索1页 + 取第1条详情
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from browser.liepin import LiepinBrowser

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_browser")


async def test_login(browser: LiepinBrowser) -> bool:
    logged_in = await browser.check_login()
    print(f"\n{'✅' if logged_in else '❌'} 登录状态: {'已登录' if logged_in else '未登录'}")
    if not logged_in:
        print("请在浏览器中扫码登录猎聘，然后重新运行测试。")
    return logged_in


async def test_search(browser: LiepinBrowser, keyword: str, max_pages: int) -> list[dict]:
    print(f"\n🔍 搜索: keyword={keyword}, max_pages={max_pages}")
    items = await browser.search_jobs(
        keyword=keyword,
        max_pages=max_pages,
        max_items=50,
        progress=lambda msg: print(f"  📊 {msg}"),
    )
    print(f"\n✅ 搜索完成，共 {len(items)} 条")

    # 验证字段完整性（与 _map_liepin 输入一致）
    required_fields = ["jobTitle", "compName", "jobLink"]
    optional_fields = ["jobSalaryText", "jobArea", "jobEduReq", "jobExpReq", "compIndustry", "compScale", "hrName"]

    if items:
        sample = items[0]
        print(f"\n📋 第1条数据样例:")
        for k in required_fields + optional_fields:
            v = sample.get(k, "❌ 缺失")
            print(f"  {k}: {v}")

        # 检查必填字段
        missing = [f for f in required_fields if not sample.get(f)]
        if missing:
            print(f"\n⚠️ 必填字段缺失: {missing}")
        else:
            print(f"\n✅ 必填字段完整")

    return items


async def test_detail(browser: LiepinBrowser, url: str) -> str | None:
    print(f"\n📄 获取详情: {url[:80]}...")
    jd = await browser.fetch_job_detail(url)
    if jd:
        print(f"✅ JD 获取成功，长度: {len(jd)} 字符")
        print(f"  前200字: {jd[:200]}...")
    else:
        print("❌ JD 获取失败")
    return jd


async def test_all(keyword: str) -> None:
    """完整流程：登录检查 → 搜索1页 → 取第1条详情"""
    browser = LiepinBrowser(headless=False)
    try:
        await browser.init()

        # 1. 登录检查
        if not await test_login(browser):
            print("\n等待 30 秒，请在浏览器中扫码登录...")
            await asyncio.sleep(30)
            if not await test_login(browser):
                return

        # 2. 搜索
        items = await test_search(browser, keyword, max_pages=1)
        if not items:
            print("❌ 搜索无结果，测试终止")
            return

        # 3. 取第1条详情
        first_url = items[0].get("jobLink", "")
        if first_url:
            await test_detail(browser, first_url)
        else:
            print("⚠️ 第1条无 URL，跳过详情测试")

        print("\n" + "=" * 50)
        print(f"✅ 端到端测试完成：搜索 {len(items)} 条，详情 {'成功' if first_url else '跳过'}")

    finally:
        await browser.close()


async def main():
    parser = argparse.ArgumentParser(description="LiepinBrowser 端到端测试")
    parser.add_argument("action", choices=["login", "search", "detail", "all"])
    parser.add_argument("--keyword", default="AI", help="搜索关键词")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--url", help="岗位详情 URL（detail 模式必填）")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    if args.action == "all":
        await test_all(args.keyword)
        return

    browser = LiepinBrowser(headless=args.headless)
    try:
        await browser.init()

        if args.action == "login":
            await test_login(browser)
        elif args.action == "search":
            await test_search(browser, args.keyword, args.max_pages)
        elif args.action == "detail":
            if not args.url:
                print("❌ detail 模式需要 --url 参数")
                return
            await test_detail(browser, args.url)
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
