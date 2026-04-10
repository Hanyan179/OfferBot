#!/usr/bin/env python3
"""猎聘扫码登录 — 打开浏览器等你扫码，成功后保存 cookie。"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from browser.liepin import LiepinBrowser

async def main():
    b = LiepinBrowser(headless=False)
    await b.init()
    page = b._page
    await page.goto("https://www.liepin.com/login", wait_until="domcontentloaded")
    # 尝试切换到二维码登录
    try:
        qr = page.locator(".switch-type-mask-img-box").first
        if await qr.is_visible():
            await qr.click()
    except Exception:
        pass
    print("\n🔑 请在浏览器中扫码登录猎聘...")
    print("   登录成功后会自动检测并保存 cookie。\n")
    for i in range(120):  # 等2分钟
        await asyncio.sleep(3)
        try:
            if await page.locator("#header-quick-menu-user-info").count() > 0:
                print("✅ 登录成功！")
                await b._save_cookies()
                await b.close()
                return
            if await page.locator("img.header-quick-menu-user-photo").count() > 0:
                print("✅ 登录成功！")
                await b._save_cookies()
                await b.close()
                return
        except Exception:
            pass
    print("⏰ 超时，请重新运行")
    await b.close()

if __name__ == "__main__":
    asyncio.run(main())
