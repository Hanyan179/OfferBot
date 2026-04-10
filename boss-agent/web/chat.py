"""
Chainlit 对话逻辑（挂载到 /chat）

接入 Agent Core：用户消息 → Planner → Executor → Step 展示工具调用
LLM 配置从 /settings 页面管理，保存在 SQLite user_preferences 表中。

集成记忆系统：
- on_chat_start: 加载记忆画像 + Skills 注入 system prompt
- on_chat_resume: 从 DataLayer 恢复对话历史 + UI 元素
- handle_user_message: 异步记忆提取（Chainlit DataLayer 自动持久化消息）
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import chainlit as cl

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from agent.bootstrap import bootstrap
from agent.context_builder import ContextBuilder
from agent.system_prompt import build_full_system_prompt
from config import load_config
from db.database import Database
from tools.data.conversation_logger import ConversationLogger
from tools.data.execution_trace import ExecutionTraceStore

logger = logging.getLogger(__name__)

SCENARIO_CARDS: list[dict[str, str]] = [
    {"emoji": "🔍", "title": "搜索岗位", "prompt": "帮我搜索上海 AI 岗位"},
    {"emoji": "📊", "title": "简历匹配", "prompt": "分析我的简历匹配度"},
    {"emoji": "👋", "title": "打招呼语", "prompt": "生成打招呼语"},
    {"emoji": "📈", "title": "投递统计", "prompt": "查看投递统计"},
]

# 厂商预设（和 app.py 保持一致）
PROVIDER_PRESETS = {
    "dashscope": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.6-plus"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": "gemini-3.1-flash-lite-preview"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
}


async def _ensure_agent_ready(db: Database, config) -> bool:
    """确保 Agent 已初始化。配置变了则重新初始化。"""
    llm_config = await _load_llm_config(db)
    if llm_config is None and config.dashscope_api_key:
        llm_config = {
            "api_key": config.dashscope_api_key,
            "base_url": config.api_base_url,
            "model": config.dashscope_llm_model,
        }
    if not llm_config:
        cl.user_session.set("agent_ready", False)
        return False
    # 配置没变且已 ready → 跳过（但必须确认 executor 还在）
    current = cl.user_session.get("current_model")
    if cl.user_session.get("agent_ready") and current == llm_config["model"] and cl.user_session.get("executor"):
        return True
    # 配置变了或未初始化 → 重新初始化
    return await _init_agent(db, **llm_config)


async def _load_llm_config(db: Database) -> dict | None:
    """从数据库读取 LLM 配置，返回 {api_key, base_url, model} 或 None。"""
    keys = ("llm_provider", "llm_api_key", "llm_base_url", "llm_model")
    result = {}
    for key in keys:
        rows = await db.execute("SELECT value FROM user_preferences WHERE key = ?", (key,))
        result[key] = rows[0]["value"] if rows else ""

    api_key = result.get("llm_api_key", "")
    if not api_key:
        logger.warning("LLM 配置缺失: api_key 为空")
        return None

    base_url = result.get("llm_base_url", "")
    model = result.get("llm_model", "")
    provider = result.get("llm_provider", "")

    # 自动填充预设
    if not base_url or not model:
        preset = PROVIDER_PRESETS.get(provider, {})
        if not base_url:
            base_url = preset.get("base_url", "")
        if not model:
            model = preset.get("model", "")

    if not base_url or not model:
        return None

    return {"api_key": api_key, "base_url": base_url, "model": model}


async def _init_agent(db: Database, api_key: str, base_url: str, model: str) -> bool:
    """用给定的配置初始化 Agent Core，成功返回 True。"""
    try:
        components = bootstrap(db=db, api_key=api_key, model=model, base_url=base_url)
        cl.user_session.set("planner", components["planner"])
        cl.user_session.set("executor", components["executor"])
        cl.user_session.set("skill_loader", components["skill_loader"])
        cl.user_session.set("registry", components["registry"])

        cl.user_session.set("agent_ready", True)
        cl.user_session.set("current_model", model)

        # 初始化 TaskMonitor（后台任务监控）
        from services.task_monitor import TaskMonitor, TaskNotification
        task_monitor = TaskMonitor()

        # 捕获当前 Chainlit context，后台 task 里需要恢复它才能发消息
        _cl_context = cl.context.session

        async def _ui_push(notif: TaskNotification) -> None:
            """后台任务完成/超时/失败 → 更新 store + 推送任务面板"""
            try:
                from chainlit.context import init_ws_context
                init_ws_context(_cl_context)
                from services.task_state import TaskStateStore
                _db = cl.user_session.get("db")
                if _db:
                    store = TaskStateStore(_db)
                    if notif.status in ("timeout", "failed"):
                        await store.update_status(notif.task_id, notif.status, notif.message)
                    await _push_task_panel(store)
            except Exception as e:
                logger.warning("任务面板推送失败: %s", e)

        task_monitor.set_ui_callback(_ui_push)
        cl.user_session.set("task_monitor", task_monitor)
        cl.user_session.set("agent_busy", False)

        return True
    except Exception as e:
        cl.user_session.set("agent_ready", False)
        await cl.Message(content=f"❌ Agent 初始化失败: {e}").send()
        return False


def _format_tool_result(data: dict) -> str:
    """将工具返回数据格式化为可读文本。"""
    clean = {}
    for k, v in data.items():
        if isinstance(v, dict):
            clean[k] = {ik: iv for ik, iv in v.items() if not str(ik).startswith("_")}
        else:
            clean[k] = v
    try:
        return json.dumps(clean, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(clean)


@cl.on_chat_resume
async def on_chat_resume(thread):
    """Chainlit 侧边栏点击历史对话时触发 — 从 DataLayer 恢复对话上下文。"""
    tid = thread.get("id") if isinstance(thread, dict) else getattr(thread, "id", "?")
    logger.info("on_chat_resume 触发, thread_id=%s", tid)
    config = load_config()
    cl.user_session.set("config", config)

    db = Database(config.db_path)
    await db.connect()
    await db.init_schema()
    cl.user_session.set("db", db)
    cl.user_session.set("trace_store", ExecutionTraceStore())

    # 从 thread["steps"] 恢复 chat_history（给 executor 用）
    history = []
    for step in (thread.get("steps") or []):
        output = step.get("output", "")
        if not output:
            continue
        step_type = step.get("type", "")
        if "user_message" in step_type:
            history.append({"role": "user", "content": output})
        elif "assistant_message" in step_type:
            history.append({"role": "assistant", "content": output})
    cl.user_session.set("chat_history", history)

    # --- 使用 ContextBuilder 构建上下文前言 ---
    ctx_builder = ContextBuilder()
    context_preamble = await ctx_builder.build_preamble(db=db)
    cl.user_session.set("context_preamble", context_preamble)

    # System prompt + Skills + Context Preamble
    skills_section = ""
    full_system_prompt = build_full_system_prompt(
        skills_prompt_section=skills_section,
        context_preamble=context_preamble,
    )
    cl.user_session.set("system_prompt", full_system_prompt)

    await _ensure_agent_ready(db, config)

    if not cl.user_session.get("agent_ready"):
        await cl.Message(
            content="⚙️ Agent 未就绪，请先在顶部导航栏点击「设置」配置 API Key，或刷新页面重试。"
        ).send()
        return

    skill_loader = cl.user_session.get("skill_loader")
    if skill_loader is not None:
        skills_section = skill_loader.to_prompt_section()
        full_system_prompt = build_full_system_prompt(
            skills_prompt_section=skills_section,
            context_preamble=context_preamble,
        )
        cl.user_session.set("system_prompt", full_system_prompt)

    if cl.user_session.get("agent_ready"):
        has_history = any(m.get("role") in ("user", "assistant") for m in history)
        if not has_history:
            if ctx_builder.has_profile:
                welcome = f"## 👋 欢迎回来，{ctx_builder.profile_name}\n\n"
                details = [d for d in [f"📍 {ctx_builder.profile_city}" if ctx_builder.profile_city else "", f"💼 {ctx_builder.profile_role}" if ctx_builder.profile_role else ""] if d]
                if details:
                    welcome += " · ".join(details) + "\n\n"
                welcome += "有什么我可以帮你的？可以继续上次的求职进展，或者告诉我新的需求。"
            else:
                welcome = (
                    "## 👋 你好，我是 MooBot\n\n"
                    "我是你的 AI 求职顾问，从认识你自己到拿到 offer，全程陪你。\n\n"
                    "我们先聊聊吧 — 你目前是在职还是离职？做什么方向的？想找什么样的工作？"
                )
            await cl.Message(content=welcome).send()

    # ---- 恢复 session 数据 ----
    elements = thread.get("elements") or []
    for el in elements:
        if el.get("type") != "custom":
            continue
        name = el.get("name", "")
        props_raw = el.get("props", "{}")
        props = json.loads(props_raw) if isinstance(props_raw, str) else (props_raw or {})
        if name == "JobList" and props.get("jobs"):
            id_map = {j["seq"]: {"id": j["id"], "title": j["title"], "company": j["company"]} for j in props["jobs"]}
            cl.user_session.set("job_id_map", id_map)


@cl.on_chat_start
async def on_chat_start():
    # 防止 WebSocket 重连导致重复执行
    if cl.user_session.get("_chat_started"):
        print(">>> on_chat_start 跳过（已启动）")
        return
    cl.user_session.set("_chat_started", True)
    print(">>> on_chat_start 触发")

    config = load_config()
    cl.user_session.set("config", config)
    cl.user_session.set("chat_history", [])
    cl.user_session.set("_conv_has_interaction", False)

    # 连接数据库
    db = Database(config.db_path)
    await db.connect()
    await db.init_schema()
    cl.user_session.set("db", db)
    cl.user_session.set("trace_store", ExecutionTraceStore())

    # Chainlit DataLayer 自动管理 thread，不需要手动创建

    # --- 使用 ContextBuilder 构建上下文前言 ---
    ctx_builder = ContextBuilder()
    context_preamble = await ctx_builder.build_preamble(db=db)
    cl.user_session.set("context_preamble", context_preamble)

    # --- 构建完整 System Prompt（基础 + 记忆指引 + Skills + 上下文前言） ---
    skills_section = ""
    full_system_prompt = build_full_system_prompt(
        skills_prompt_section=skills_section,
        context_preamble=context_preamble,
    )
    cl.user_session.set("system_prompt", full_system_prompt)

    # 尝试从数据库读取 LLM 配置
    await _ensure_agent_ready(db, config)

    # --- Agent 初始化后，用 bootstrap 的 skill_loader 重新生成 Skills 摘要 ---
    skill_loader = cl.user_session.get("skill_loader")
    if skill_loader is not None:
        skills_section = skill_loader.to_prompt_section()
        full_system_prompt = build_full_system_prompt(
            skills_prompt_section=skills_section,
            context_preamble=context_preamble,
        )
        cl.user_session.set("system_prompt", full_system_prompt)

    if not cl.user_session.get("agent_ready"):
        # 未配置 — 固定欢迎语 + 引导配置
        await cl.Message(
            content="## 👋 你好，我是 MooBot\n\n"
            "我是你的 AI 求职顾问，可以帮你认识自己、搜索岗位、分析匹配度、准备面试。\n\n"
            "⚙️ 请先点击顶部导航栏的「设置」配置 API Key，保存后会自动回到对话。"
        ).send()
    else:
        if ctx_builder.has_profile:
            welcome = f"## 👋 欢迎回来，{ctx_builder.profile_name}\n\n"
            details = []
            if ctx_builder.profile_city:
                details.append(f"📍 {ctx_builder.profile_city}")
            if ctx_builder.profile_role:
                details.append(f"💼 {ctx_builder.profile_role}")
            if details:
                welcome += " · ".join(details) + "\n\n"
            welcome += "有什么我可以帮你的？可以继续上次的求职进展，或者告诉我新的需求。"
        else:
            welcome = (
                "## 👋 你好，我是 MooBot\n\n"
                "我是你的 AI 求职顾问，从认识你自己到拿到 offer，全程陪你。\n\n"
                "我们先聊聊吧 — 你目前是在职还是离职？做什么方向的？想找什么样的工作？"
            )

        await cl.Message(content=welcome).send()


@cl.action_callback("scenario_action")
async def on_scenario_action(action: cl.Action):
    prompt = action.payload.get("prompt", "")
    if prompt:
        await cl.Message(content=prompt, author="user", type="user_message").send()
        await handle_user_message(prompt)


@cl.action_callback("action_card_submit")
async def on_action_card_submit(action: cl.Action):
    """用户在 ActionCard 上确认执行后的回调。"""
    payload = action.payload or {}
    card_type = payload.get("card_type", "unknown")
    params = payload.get("params", {})
    job_ids = payload.get("job_ids", [])

    card_el = cl.user_session.get(f"action_card_{card_type}")
    if card_el:
        card_el.props["status"] = "executing"
        await card_el.update()

    # 特殊流程（有复杂逻辑的 card_type）
    if card_type == "start_task":
        await _execute_start_task(params, card_el)
    elif card_type == "fetch_detail":
        await _execute_fetch_detail(params, job_ids, card_el)
    elif card_type == "deliver":
        await _execute_deliver(params, job_ids, card_el)
    else:
        # 通用路径：通过 tool_name 直接调 Tool，结果进任务面板
        tool_name = payload.get("tool_name")
        await _execute_generic_tool(tool_name or card_type, params, card_el)


async def _execute_generic_tool(tool_name: str, params: dict, card_el):
    """通用 Tool 执行：查找 Tool → 执行 → 结果写任务面板。"""
    import time as _time

    from services.task_state import TaskInfo, TaskStateStore

    registry = cl.user_session.get("registry")
    db = cl.user_session.get("db")

    if not registry or not registry.has_tool(tool_name):
        if card_el:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = f"未知工具: {tool_name}"
            await card_el.update()
        return

    # 注册任务到面板并推送
    task_id = f"{tool_name}-{int(_time.time())}"
    store = TaskStateStore(db)
    tool = registry.get_tool(tool_name)
    await store.upsert(TaskInfo(
        task_id=task_id, name=tool.display_name,
        platform="local", status="running", progress_text="执行中",
    ))
    await _push_task_panel(store)

    try:
        context = {"db": db, "browser": cl.user_session.get("browser")}
        result = await tool.execute(params, context)
        if isinstance(result, dict) and result.get("action") == "confirm_required":
            await store.update_status(task_id, "failed", "确认参数丢失")
            if card_el:
                card_el.props["status"] = "failed"
                card_el.props["result_message"] = "确认参数丢失，请重试"
                await card_el.update()
            await _push_task_panel(store)
            return
        success = result.get("success", True) if isinstance(result, dict) else True
        msg = result.get("message", "完成") if isinstance(result, dict) else "完成"
        await store.update_status(task_id, "completed" if success else "failed", msg)
        if card_el:
            card_el.props["status"] = "completed" if success else "failed"
            card_el.props["result_message"] = msg
            await card_el.update()
    except Exception as e:
        await store.update_status(task_id, "failed", str(e))
        if card_el:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = str(e)
            await card_el.update()
    await _push_task_panel(store)


async def _push_task_panel(store):
    """推送任务面板更新到前端"""
    tasks = await store.get_active()
    await cl.send_window_message(json.dumps({
        "type": "task_panel_update",
        "tasks": tasks,
    }, ensure_ascii=False, default=str))


async def _refresh_job_list_element(db):
    """从数据库重新查询状态，刷新对话中最近的 JobList 卡片。"""
    job_list_el = cl.user_session.get("last_job_list_element")
    if not job_list_el or not hasattr(job_list_el, "props") or not job_list_el.props.get("jobs"):
        return
    ids = [j["id"] for j in job_list_el.props["jobs"]]
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    rows = await db.execute(
        f"SELECT id,"
        f" CASE WHEN raw_jd IS NOT NULL AND raw_jd != '' THEN 1 ELSE 0 END as has_jd,"
        f" CASE WHEN match_detail IS NOT NULL AND match_detail != '' THEN 1 ELSE 0 END as has_analysis"
        f" FROM jobs WHERE id IN ({placeholders})",
        tuple(ids),
    )
    status_map = {r["id"]: r for r in rows}
    for j in job_list_el.props["jobs"]:
        s = status_map.get(j["id"])
        if s:
            j["has_jd"] = bool(s["has_jd"])
            j["has_analysis"] = bool(s["has_analysis"])
    try:
        await job_list_el.update()
    except Exception:
        pass


# salaryCode → 月薪下限(K)
_SALARY_CODE_MIN_K = {
    "1": 0, "2": 8, "3": 12, "4": 17, "5": 25, "6": 42, "7": 83,
}


async def _post_sync_filter(db, config_data: dict, sync_result: dict) -> int:
    """同步后过滤不匹配的岗位，返回删除数量。"""
    clauses: list[str] = []
    values: list = []

    # 城市过滤（模糊匹配）
    city = config_data.get("city")
    if city:
        # 取第一个城市关键词（可能是"上海"或编码）
        city_kw = city.split("$")[0].split(",")[0].strip()
        if city_kw and not city_kw.isdigit():
            clauses.append("city NOT LIKE ?")
            values.append(f"%{city_kw}%")

    # 薪资过滤：岗位最高薪资 < 用户期望下限 → 删除
    salary_code = config_data.get("salaryCode")
    if salary_code:
        # 取最低的 code（如 "5" 或 "15$30" 格式）
        code = salary_code.split("$")[0] if "$" in salary_code else salary_code
        min_k = _SALARY_CODE_MIN_K.get(code)
        if min_k and min_k > 0:
            clauses.append("(salary_max IS NOT NULL AND salary_max > 0 AND salary_max < ?)")
            values.append(min_k)

    if not clauses:
        return 0

    # 只删最近同步的（10分钟内更新的）
    where = " OR ".join(f"({c})" for c in clauses)
    count_sql = (
        f"SELECT COUNT(*) as cnt FROM jobs WHERE ({where}) "
        f"AND updated_at > datetime('now', '-10 minutes')"
    )
    rows = await db.execute(count_sql, tuple(values))
    count = rows[0]["cnt"] if rows else 0
    if count == 0:
        return 0

    sql = (
        f"DELETE FROM jobs WHERE ({where}) "
        f"AND updated_at > datetime('now', '-10 minutes')"
    )
    await db.execute_write(sql, tuple(values))
    return count


async def _execute_start_task(params: dict, card_el):
    """执行采集：直接用 Playwright 搜索猎聘，结果写入本地 DB"""
    import time as _time

    browser = cl.user_session.get("browser")
    if not browser:
        if card_el:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = "浏览器未初始化"
            await card_el.update()
        return

    db = cl.user_session.get("db")
    platform = "liepin"

    if card_el:
        card_el.props["status"] = "completed"
        card_el.props["result_message"] = "采集任务已启动！进度请看右侧面板 →"
        await card_el.update()

    # 注册任务到面板
    from services.task_state import TaskStateStore, TaskInfo
    task_id = f"{platform}-{int(_time.time())}"
    store = TaskStateStore(db) if db else None
    if store:
        await store.upsert(TaskInfo(
            task_id=task_id, name="采集岗位列表",
            platform=platform, status="running", progress_text="启动中...",
        ))
        await _push_task_panel(store)

    # 在后台执行搜索
    import asyncio

    async def _run_scrape():
        try:
            keyword = params.get("keywords", "")
            if isinstance(keyword, list):
                keyword = ",".join(keyword)

            from tools.crawler.scrape_jobs import ScrapeJobsTool
            from tools.crawler.job_mapping import map_liepin, upsert_jobs

            items = await browser.search_jobs(
                keyword=keyword,
                city_code=params.get("city", ""),
                salary_code=params.get("salaryCode", ""),
                max_pages=params.get("maxPages", 2),
                max_items=params.get("maxItems", 100),
                progress=lambda msg: asyncio.ensure_future(_update_progress(msg)),
            )

            if not items:
                if store:
                    await store.update_status(task_id, "completed", "未找到岗位")
                    await _push_task_panel(store)
                return

            # 写入 DB
            rows = [map_liepin(item) for item in items]
            inserted, updated = await upsert_jobs(db, rows)

            # 同步后过滤
            config_data = {k: params[k] for k in ("keywords", "city", "salaryCode") if k in params and params[k]}
            filtered = await _post_sync_filter(db, config_data, {"data": {"inserted": inserted}}) if config_data else 0

            msg = f"采集 {len(items)} 条，新增 {inserted}"
            if filtered:
                msg += f"，过滤 {filtered} 条"

            if store:
                await store.update_status(task_id, "completed", msg)
                await _push_task_panel(store)
            if card_el:
                card_el.props["status"] = "completed"
                card_el.props["result_message"] = msg
                try:
                    await card_el.update()
                except Exception:
                    pass

        except Exception as e:
            logger.error("采集任务失败: %s", e)
            if store:
                await store.update_status(task_id, "failed", str(e))
                await _push_task_panel(store)

    async def _update_progress(msg: str):
        if store:
            await store.update_progress(task_id, msg)
            await _push_task_panel(store)

    # 后台执行，不阻塞 UI
    asyncio.create_task(_run_scrape())


async def _execute_fetch_detail(params: dict, job_ids: list, card_el):
    """执行批量获取岗位详情 — 直接用 Playwright"""
    import time as _time

    if not job_ids:
        if card_el:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = "未选择岗位"
            await card_el.update()
        return

    db = cl.user_session.get("db")
    browser = cl.user_session.get("browser")
    if not browser:
        if card_el:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = "浏览器未初始化"
            await card_el.update()
        return

    if card_el:
        card_el.props["status"] = "completed"
        card_el.props["result_message"] = "详情采集已启动！进度请看右侧面板 →"
        await card_el.update()

    from services.task_state import TaskStateStore, TaskInfo
    task_id = f"fetch-detail-{int(_time.time())}"
    store = TaskStateStore(db) if db else None
    if store:
        await store.upsert(TaskInfo(
            task_id=task_id, name=f"采集岗位详情（{len(job_ids)}条）",
            platform="liepin", status="running", progress_text=f"0/{len(job_ids)}",
        ))
        await _push_task_panel(store)

    force = params.get("force", False)
    placeholders = ",".join("?" * len(job_ids))
    rows = await db.execute(
        f"SELECT id, url, title, raw_jd FROM jobs WHERE id IN ({placeholders})",
        tuple(job_ids),
    )
    if not rows:
        msg = "未找到对应岗位"
        if store:
            await store.update_status(task_id, "failed", msg)
            await _push_task_panel(store)
        return

    success_count = 0
    fail_count = 0
    skipped_count = 0

    for row in rows:
        url = row.get("url", "")
        local_id = row["id"]
        raw_jd = row.get("raw_jd") or ""

        if raw_jd and not force:
            skipped_count += 1
        elif not url or url == "#":
            fail_count += 1
        else:
            jd_text = await browser.fetch_job_detail(url)
            if jd_text:
                await db.execute_write(
                    "UPDATE jobs SET raw_jd = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (jd_text, local_id),
                )
                success_count += 1
            else:
                fail_count += 1

        done = success_count + fail_count + skipped_count
        if store:
            await store.update_progress(task_id, f"{done}/{len(rows)} 成功{success_count} 失败{fail_count}")
            await _push_task_panel(store)

    msg = f"完成：获取 {success_count} 条，跳过 {skipped_count} 条"
    if fail_count:
        msg += f"，失败 {fail_count} 条"
    final_status = "completed" if success_count > 0 or skipped_count > 0 else "failed"

    if store:
        await store.update_status(task_id, final_status, msg)
        await _push_task_panel(store)
    if card_el:
        card_el.props["status"] = final_status
        card_el.props["result_message"] = msg
        try: await card_el.update()
        except Exception: pass

    if success_count > 0:
        await _refresh_job_list_element(db)


async def _execute_deliver(params: dict, job_ids: list, card_el):
    """执行投递打招呼"""
    if not job_ids:
        if card_el:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = "未选择岗位"
            await card_el.update()
        return

    from tools.crawler.deliver import DeliverTool
    db = cl.user_session.get("db")
    result = await DeliverTool().execute(
        {"platform": "liepin", "job_ids": job_ids},
        {"browser": cl.user_session.get("browser"), "db": db, "llm_client": cl.user_session.get("executor")._llm if cl.user_session.get("executor") else None},
    )
    if card_el:
        if result.get("success"):
            card_el.props["status"] = "completed"
            card_el.props["result_message"] = f"投递完成！成功 {result.get('delivered', 0)} 条"
        else:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = result.get("error", "投递失败")
        await card_el.update()



@cl.action_callback("action_card_cancel")
async def on_action_card_cancel(action: cl.Action):
    """用户取消操作卡片"""
    card_type = (action.payload or {}).get("card_type", "unknown")
    card_el = cl.user_session.get(f"action_card_{card_type}")
    if card_el:
        card_el.props["status"] = "failed"
        card_el.props["result_message"] = "已取消"
        await card_el.update()


async def _parse_file(file_path: str, file_name: str = "") -> str | None:
    """解析上传的文件，返回文本内容。支持 .md/.txt/.pdf/.doc/.docx"""
    from pathlib import Path as _P
    ext = _P(file_name or file_path).suffix.lower()

    try:
        if ext in (".md", ".txt", ".csv", ".json"):
            return _P(file_path).read_text(encoding="utf-8")

        if ext == ".pdf":
            import pdfplumber
            texts = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        texts.append(text)
            return "\n\n".join(texts) if texts else None

        if ext in (".docx", ".doc"):
            from docx import Document as DocxDocument
            doc = DocxDocument(file_path)
            texts = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(texts) if texts else None

        # 未知格式，尝试当纯文本读
        try:
            return _P(file_path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, Exception):
            return None

    except Exception as e:
        return f"[文件解析失败: {file_name or file_path}, 错误: {e}]"


@cl.on_message
async def on_message(message: cl.Message):
    # 处理附件：解析上传的文件内容，拼接到消息文本中
    file_texts = []
    if message.elements:
        for elem in message.elements:
            if not hasattr(elem, "path") or not elem.path:
                continue
            parsed = await _parse_file(elem.path, getattr(elem, "name", ""))
            if parsed:
                file_texts.append(parsed)

    content = message.content or ""
    if file_texts:
        attachment_block = "\n\n".join(file_texts)
        if content:
            content = f"{content}\n\n---\n📎 附件内容：\n\n{attachment_block}"
        else:
            content = f"📎 附件内容：\n\n{attachment_block}"

    await handle_user_message(content)


async def handle_user_message(content: str):
    """处理用户消息：直接调 Executor.chat()，LLM 自行决定回复文本 or 调工具。"""
    if not content.strip():
        return

    history = cl.user_session.get("chat_history", [])
    history.append({"role": "user", "content": content})

    agent_ready = cl.user_session.get("agent_ready", False)

    if not agent_ready:
        # 尝试重新加载配置（用户可能刚改了设置）
        db = cl.user_session.get("db")
        config = cl.user_session.get("config")
        if db and config:
            await _ensure_agent_ready(db, config)
            agent_ready = cl.user_session.get("agent_ready", False)

    if not agent_ready:
        await cl.Message(
            content="⚠️ Agent 未就绪，请先在顶部导航栏点击「⚙️ 设置」配置 API Key。"
        ).send()
        return

    # Chainlit DataLayer 自动持久化消息（create_step），不需要手动保存

    executor = cl.user_session.get("executor")
    system_prompt = cl.user_session.get("system_prompt")

    if not executor:
        logger.error("executor=None, agent_ready=%s", cl.user_session.get("agent_ready"))
        await cl.Message(content="❌ Agent 未初始化，请刷新页面重试。").send()
        return

    current_step: cl.Step | None = None
    assistant_text = ""
    pending_elements: list = []
    db = cl.user_session.get("db")

    # --- 执行轨迹收集 ---
    trace_events: list[dict] = []
    trace_started_at = datetime.now()

    # --- 对话日志 ---
    conv_logger: ConversationLogger | None = None
    thread_id = getattr(cl.context.session, "thread_id", None)
    if thread_id:
        conv_logger = ConversationLogger(thread_id)
        conv_logger.begin_turn(content)

    # 标记 agent 正在处理中（后台任务通知会据此判断是否直接推送 UI）
    cl.user_session.set("agent_busy", True)

    async for event in executor.chat(messages=history, context={"db": db, "llm_client": executor._llm, "browser": cl.user_session.get("browser"), "task_monitor": cl.user_session.get("task_monitor"), "agent_busy_check": lambda: cl.user_session.get("agent_busy", False), "conversation_logger": conv_logger}, system_prompt=system_prompt):
        # 收集事件到 trace
        trace_events.append(event.to_dict())

        if event.type == "thinking":
            # 思考过程 — 折叠展示
            thinking_text = event.data.get("content", "")
            if thinking_text:
                async with cl.Step(name="💭 思考中", type="llm") as think_step:
                    think_step.output = thinking_text

        elif event.type == "assistant_message":
            # LLM 的文本回复
            text = event.data.get("content", "")
            if text:
                assistant_text = text
                await cl.Message(content=text).send()
            # 不管有没有文字，都把攒着的 UI 元素发出去
            for el in pending_elements:
                await cl.Message(content="\u200b", elements=[el]).send()
            pending_elements = []

        elif event.type == "tool_start":
            tool_name = event.data.get("tool_name", "unknown")
            tool_args = event.data.get("arguments", {})
            registry = cl.user_session.get("registry")
            display_name = registry.get_display_name(tool_name) if registry else tool_name
            current_step = cl.Step(name=f"🔧 {display_name}", type="tool")
            current_step.input = json.dumps(tool_args, ensure_ascii=False, indent=2) if tool_args else "(无参数)"
            await current_step.__aenter__()

        elif event.type == "tool_result":
            success = event.data.get("success", False)
            data = event.data.get("data", {})

            if current_step is not None:
                if success:
                    # 分流结果只在 Step 里显示 for_agent 摘要，不显示 for_ui 的完整数据
                    step_data = data
                    if isinstance(data, dict):
                        for v in data.values():
                            if isinstance(v, dict) and "for_agent" in v:
                                step_data = {k: v.get("for_agent") for k, v in data.items() if isinstance(v, dict) and "for_agent" in v}
                                break
                    current_step.output = _format_tool_result(step_data)
                else:
                    current_step.output = "❌ 执行失败"
                await current_step.__aexit__(None, None, None)
                current_step = None

        elif event.type == "action_card":
            card_data = event.data
            card_type = card_data.get("card_type", "unknown")
            element = cl.CustomElement(name="ActionCard", props=card_data, display="inline")
            cl.user_session.set(f"action_card_{card_type}", element)
            # 直接发送（不攒到 pending，因为 confirm_required 不会有 assistant_message）
            await cl.Message(content="请确认以下操作：", elements=[element]).send()

        elif event.type == "ui_render":
            for_ui = event.data.get("for_ui", {})
            element_name = for_ui.pop("element_name", None)
            if element_name:
                element = cl.CustomElement(name=element_name, props=for_ui, display="inline")
                pending_elements.append(element)
                # JobList 特殊处理：维护序号→ID 映射供后续对话引用
                if element_name == "JobList" and for_ui.get("jobs"):
                    id_map = {}
                    for j in for_ui["jobs"]:
                        id_map[j["seq"]] = {"id": j["id"], "title": j["title"], "company": j["company"]}
                    cl.user_session.set("job_id_map", id_map)
                    cl.user_session.set("last_job_list_element", element)

        elif event.type == "error":
            error_text = event.data.get("message", "")
            await cl.Message(content=f"❌ {error_text}").send()
            if current_step is not None:
                current_step.output = f"错误: {error_text}"
                await current_step.__aexit__(None, None, None)
                current_step = None

        elif event.type == "max_turns_reached":
            await cl.Message(content="⚠️ 达到最大工具调用轮数，已停止。").send()

        elif event.type == "task_notification":
            # 后台任务通知 → 推送任务面板
            from services.task_state import TaskStateStore
            if db:
                await _push_task_panel(TaskStateStore(db))

    # agent 处理完毕
    cl.user_session.set("agent_busy", False)

    # 兜底：如果还有未发的 UI 元素（AI 没有文字回复的情况）
    if pending_elements:
        for el in pending_elements:
            await cl.Message(content="\u200b", elements=[el]).send()
        pending_elements = []

    # 记录 assistant 回复到历史
    if assistant_text:
        history.append({"role": "assistant", "content": assistant_text})

    # --- 结束对话日志轮次 ---
    if conv_logger:
        conv_logger.end_turn(assistant_text or "(no reply)")

    # --- 持久化执行轨迹 ---
    trace_store: ExecutionTraceStore | None = cl.user_session.get("trace_store")
    if trace_store and thread_id and trace_events:
        try:
            trace_store.save_trace(
                conversation_id=thread_id,
                user_message=content,
                events=trace_events,
                started_at=trace_started_at,
                finished_at=datetime.now(),
            )
        except Exception as e:
            logger.warning("持久化执行轨迹失败: %s", e)

    cl.user_session.set("chat_history", history)

    # --- 记忆提取标记：本对话流结束时（on_chat_end 或新建对话时）统一提取 ---
    # handle_user_message 里不触发提取，只在对话流切换时执行
    cl.user_session.set("_conv_has_interaction", True)


def _launch_memory_extraction(history: list[dict], conversation_id: str) -> None:
    """
    异步启动 MemoryExtractor，不阻塞主对话线程。
    传入一整轮对话的全部 user/assistant 消息，子 agent 一次性总结。
    """
    try:
        executor = cl.user_session.get("executor")
        if executor is None:
            logger.warning("🧠 无法启动记忆提取: executor 为 None")
            return
        llm_client = executor._llm

        from agent.memory_extractor import MemoryExtractor
        extractor = MemoryExtractor(llm_client=llm_client)

        # 传入整轮对话的 user/assistant 消息
        messages = [m for m in history if m.get("role") in ("user", "assistant")]
        if not messages:
            logger.info("🧠 对话无 user/assistant 消息，跳过提取")
            return

        context = {"conversation_id": conversation_id}

        logger.info("🧠 启动记忆提取任务，对话 %s，消息数: %d", conversation_id, len(messages))
        asyncio.create_task(_run_extraction(extractor, messages, context))
    except Exception as e:
        logger.error("🧠 启动记忆提取失败: %s", e, exc_info=True)


async def _run_extraction(
    extractor,
    messages: list[dict],
    context: dict,
) -> None:
    """运行记忆提取，捕获所有异常。"""
    try:
        logger.info("🧠 开始记忆提取，消息数: %d, 会话: %s", len(messages), context.get("conversation_id", "?"))
        await extractor.extract(messages, context)
        logger.info("🧠 记忆提取完成")
    except Exception as e:
        logger.error("🧠 记忆提取执行失败: %s", e, exc_info=True)
