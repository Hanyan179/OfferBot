"""
LiepinBrowser — 猎聘 Playwright 浏览器自动化

核心功能：搜索岗位列表、获取 JD 详情、投递打招呼。
参考 Java 实现：reference-crawler/src/main/java/com/getjobs/worker/liepin/Liepin.java
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from playwright.async_api import Page, BrowserContext, async_playwright, Playwright

logger = logging.getLogger(__name__)

# 猎聘页面选择器（对应 Java Locators.java）
PAGINATION_BOX = ".list-pagination-box"
NEXT_PAGE = "li.ant-pagination-next"
SUBSCRIBE_CLOSE_BTN = "div[class*='subscribe-close-btn']"
JOB_CARDS = "div[class*='job-card-pc-container']"
CHAT_HEADER = ".__im_basic__header-wrap"
CHAT_CLOSE = "div.__im_basic__contacts-title svg"
CHAT_INPUT = ".__im_basic__editor .ql-editor"
CHAT_SEND_BTN = ".__im_basic__send-btn"

# 登录检测选择器
LOGIN_ENTRY = "#header-quick-menu-login, a[href*='login'], a[data-key='login']"
USER_INFO = "#header-quick-menu-user-info"
USER_PHOTO = "img.header-quick-menu-user-photo, .header-quick-menu-user-photo"

COOKIE_FILE = "data/liepin_cookies.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"


class LiepinBrowser:
    """猎聘浏览器自动化，管理 Playwright 生命周期。"""

    def __init__(self, cookie_path: str | None = None, headless: bool = False) -> None:
        self._cookie_path = Path(cookie_path or COOKIE_FILE)
        self._headless = headless
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._api_items: list[dict] = []  # 拦截到的 API 数据

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """启动浏览器，加载 cookie。"""
        self._pw = await async_playwright().start()
        browser = await self._pw.chromium.launch(
            headless=self._headless,
            slow_mo=50,
            args=["--start-maximized"],
        )
        self._context = await browser.new_context(
            viewport=None,
            user_agent=UA,
        )
        # 加载 cookie
        if self._cookie_path.exists():
            try:
                cookies = json.loads(self._cookie_path.read_text())
                await self._context.add_cookies(cookies)
                logger.info("已加载 %d 条 cookie", len(cookies))
            except Exception as e:
                logger.warning("加载 cookie 失败: %s", e)

        self._page = await self._context.new_page()
        self._page.set_default_timeout(30_000)

        # 注册 API 拦截（参考 Liepin.java:prepare()）
        self._page.on("response", self._on_response)

    async def close(self) -> None:
        """保存 cookie 并关闭浏览器。"""
        if self._context:
            await self._save_cookies()
            await self._context.close()
        if self._pw:
            await self._pw.stop()
        self._page = None
        self._context = None
        self._pw = None

    async def _save_cookies(self) -> None:
        if not self._context:
            return
        try:
            cookies = await self._context.cookies()
            self._cookie_path.parent.mkdir(parents=True, exist_ok=True)
            self._cookie_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
            logger.info("已保存 %d 条 cookie", len(cookies))
        except Exception as e:
            logger.warning("保存 cookie 失败: %s", e)

    # ------------------------------------------------------------------
    # API 拦截（参考 Liepin.java 的 onResponse 监控）
    # ------------------------------------------------------------------

    async def _on_response(self, response) -> None:
        """拦截猎聘搜索 API 响应，解析岗位数据。"""
        url = response.url
        if ("com.liepin.searchfront4c.pc-search-job" not in url
                or "pc-search-job-cond-init" in url):
            return
        if response.status != 200:
            return
        try:
            data = await response.json()
            self._parse_api_data(data)
        except Exception as e:
            logger.warning("解析猎聘 API 响应失败: %s", e)

    def _parse_api_data(self, data: dict) -> None:
        """解析猎聘搜索 API JSON（参考 Liepin.java:parseAndPersistLiepinData）。"""
        # 兼容两种结构
        card_list = (data.get("data", {}).get("data", {}).get("jobCardList")
                     or data.get("data", {}).get("jobCardList"))
        if not isinstance(card_list, list):
            return

        self._api_items.clear()
        for item in card_list:
            job = item.get("job", {})
            comp = item.get("comp", {})
            recruiter = item.get("recruiter", {})
            job_id = job.get("jobId")
            if not job_id:
                continue
            self._api_items.append({
                "jobId": job_id,
                "jobTitle": job.get("title"),
                "jobLink": job.get("link"),
                "jobSalaryText": job.get("salary"),
                "jobArea": job.get("dq"),
                "jobEduReq": job.get("requireEduLevel"),
                "jobExpReq": job.get("requireWorkYears"),
                "compName": comp.get("compName"),
                "compIndustry": comp.get("compIndustry"),
                "compScale": comp.get("compScale"),
                "hrName": recruiter.get("recruiterName"),
                "hrTitle": recruiter.get("recruiterTitle"),
            })

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------

    async def check_login(self) -> bool:
        """检查猎聘登录状态（参考 PlaywrightManager:checkIfLiepinLoggedIn）。"""
        page = self._page
        if not page:
            return False
        try:
            await page.goto("https://www.liepin.com/", wait_until="domcontentloaded", timeout=15_000)
        except Exception:
            pass
        # 等待页面渲染（头部导航需要 JS 渲染）
        await asyncio.sleep(3)
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass

        # 有用户信息 → 已登录（优先检测正向信号）
        try:
            if await page.locator(USER_INFO).count() > 0:
                return True
        except Exception:
            pass
        try:
            if await page.locator(USER_PHOTO).count() > 0:
                return True
        except Exception:
            pass
        # 有登录入口 → 未登录
        try:
            if await page.locator(LOGIN_ENTRY).first.is_visible():
                return False
        except Exception:
            pass
        # 兜底：无登录入口 → 已登录
        try:
            if await page.locator(LOGIN_ENTRY).count() == 0:
                return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # 核心功能 1：搜索岗位列表
    # ------------------------------------------------------------------

    async def search_jobs(
        self,
        keyword: str,
        city_code: str = "",
        salary_code: str = "",
        max_pages: int = 2,
        max_items: int = 100,
        progress: Callable[[str], Any] | None = None,
    ) -> list[dict]:
        """
        搜索猎聘岗位列表，返回原始字段列表。

        返回的 dict 字段与现有 _map_liepin 输入格式一致：
        jobTitle, compName, jobSalaryText, jobArea, jobLink, jobEduReq, jobExpReq,
        compIndustry, compScale, hrName, hrTitle
        """
        page = self._page
        if not page:
            raise RuntimeError("浏览器未初始化，请先调用 init()")

        all_items: list[dict] = []

        # 构建搜索 URL（参考 Liepin.java:getSearchUrl）
        url = "https://www.liepin.com/zhaopin/?"
        params = []
        if city_code:
            params += [f"city={city_code}", f"dq={city_code}"]
        if salary_code:
            params.append(f"salaryCode={salary_code}")
        params.append("currentPage=0")
        params.append(f"key={keyword}")
        url += "&".join(params)

        await page.goto(url, wait_until="domcontentloaded")

        for page_num in range(max_pages):
            if len(all_items) >= max_items:
                break

            # 等待岗位卡片加载
            try:
                await page.wait_for_selector(JOB_CARDS, state="attached", timeout=15_000)
            except Exception:
                logger.warning("第 %d 页未找到岗位卡片", page_num + 1)
                break

            # 等待 API 响应（拦截器会填充 _api_items）
            try:
                await page.wait_for_response(
                    lambda r: "com.liepin.searchfront4c.pc-search-job" in r.url and r.status == 200,
                    timeout=10_000,
                )
            except Exception:
                pass
            await asyncio.sleep(1)  # 等待拦截器处理完

            # 关闭订阅弹窗
            try:
                close_btn = page.locator(SUBSCRIBE_CLOSE_BTN)
                if await close_btn.count() > 0:
                    await close_btn.click()
            except Exception:
                pass

            # 收集本页数据
            if self._api_items:
                all_items.extend(self._api_items)
                if progress:
                    progress(f"第 {page_num + 1} 页：获取 {len(self._api_items)} 条")
                logger.info("第 %d 页：获取 %d 条，累计 %d 条", page_num + 1, len(self._api_items), len(all_items))

            # 翻页（参考 Liepin.java:submit 的翻页逻辑）
            if page_num < max_pages - 1 and len(all_items) < max_items:
                try:
                    pagination = page.locator(PAGINATION_BOX)
                    next_li = pagination.locator(NEXT_PAGE)
                    if await next_li.count() == 0:
                        break
                    cls = await next_li.first.get_attribute("class") or ""
                    if "ant-pagination-disabled" in cls:
                        break
                    btn = next_li.first.locator("button.ant-pagination-item-link")
                    if await btn.count() > 0:
                        await btn.first.click()
                    else:
                        await next_li.first.click()
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning("翻页失败: %s", e)
                    break

        await self._save_cookies()
        return all_items[:max_items]

    # ------------------------------------------------------------------
    # 核心功能 2：获取岗位 JD 详情
    # ------------------------------------------------------------------

    async def fetch_job_detail(self, url: str) -> str | None:
        """
        打开岗位详情页，返回 JD 文本。

        参考 Liepin.java:fetchJobDetail()
        """
        page = self._page
        if not page:
            raise RuntimeError("浏览器未初始化")

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_load_state("networkidle", timeout=10_000)
            await asyncio.sleep(2)

            # 猎聘详情页选择器（新旧版本兼容）
            selectors = [
                "[class*='job-intro']",
                "[class*='job-desc']",
                "[class*='job-detail']",
                "[class*='job-require']",
                "[class*='position-desc']",
                "[class*='position-detail']",
                ".job-intro-container",
                ".job-description",
                ".job-detail-description",
                ".job-item-des",
            ]

            # 等待任意选择器出现
            wait_sel = ", ".join(selectors)
            try:
                await page.wait_for_selector(wait_sel, state="attached", timeout=10_000)
            except Exception:
                pass

            for sel in selectors:
                try:
                    loc = page.locator(sel)
                    count = await loc.count()
                    for i in range(count):
                        text = await loc.nth(i).inner_text()
                        if text and len(text.strip()) > 50:
                            logger.info("JD 抓取成功，选择器: %s，长度: %d", sel, len(text.strip()))
                            return text.strip()
                except Exception:
                    continue

            # 兜底：body 文本
            try:
                body = await page.locator("body").inner_text()
                if body and len(body.strip()) > 100:
                    return body.strip()
            except Exception:
                pass

            logger.warning("未能提取 JD: %s", url)
            return None
        except Exception as e:
            logger.error("获取岗位详情失败: %s - %s", url, e)
            return None

    # ------------------------------------------------------------------
    # 核心功能 3：投递打招呼
    # ------------------------------------------------------------------

    async def deliver(self, url: str, message: str = "") -> bool:
        """
        在岗位详情页执行打招呼。

        参考 Liepin.java:deliverByJobs()
        """
        page = self._page
        if not page:
            raise RuntimeError("浏览器未初始化")

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_load_state("networkidle", timeout=10_000)
            await asyncio.sleep(2)

            # 找"立即沟通"或"聊一聊"按钮
            btn = page.locator("button:has-text('立即沟通'), button:has-text('聊一聊')").first
            if await btn.count() == 0 or not await btn.is_visible():
                logger.info("未找到沟通按钮: %s", url)
                return False

            await btn.click()
            await asyncio.sleep(1)

            # 等待聊天窗口
            try:
                await page.wait_for_selector(CHAT_HEADER, timeout=3_000)
            except Exception:
                pass

            # 发送自定义消息
            if message:
                try:
                    input_el = page.locator(CHAT_INPUT).first
                    if await input_el.count() > 0 and await input_el.is_visible():
                        await input_el.click()
                        await input_el.evaluate(
                            "(el, msg) => { el.innerHTML = '<p>' + msg + '</p>'; el.dispatchEvent(new Event('input')); }",
                            message,
                        )
                        await asyncio.sleep(1)
                        send_btn = page.locator(CHAT_SEND_BTN).first
                        if await send_btn.count() > 0:
                            await send_btn.click()
                            await asyncio.sleep(1)
                except Exception as e:
                    logger.warning("发送自定义消息失败: %s", e)

            # 关闭聊天窗口
            try:
                close = page.locator(CHAT_CLOSE)
                if await close.count() > 0:
                    await asyncio.sleep(1)
                    await close.click()
            except Exception:
                pass

            return True
        except Exception as e:
            logger.error("投递失败: %s - %s", url, e)
            return False
