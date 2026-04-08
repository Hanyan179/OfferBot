"""
Chainlit 对话逻辑（挂载到 /chat）

接入 Agent Core：用户消息 → Planner → Executor → Step 展示工具调用
LLM 配置从 /settings 页面管理，保存在 SQLite user_preferences 表中。

集成记忆系统：
- on_chat_start: 恢复对话历史 + 加载记忆画像 + Skills 注入 system prompt
- handle_user_message: 消息持久化到 JSONL + 异步记忆提取
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

from config import load_config
from db.database import Database
from agent.bootstrap import bootstrap
from tools.data.chat_history import ChatHistoryStore
from tools.data.conversation_logger import ConversationLogger
from tools.data.execution_trace import ExecutionTraceStore
from tools.data.memory_tools import GetUserCognitiveModelTool
from agent.system_prompt import build_full_system_prompt

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
    # 配置没变且已 ready → 跳过
    current = cl.user_session.get("current_model")
    if cl.user_session.get("agent_ready") and current == llm_config["model"]:
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
        cl.user_session.set("getjob_client", components["getjob_client"])
        cl.user_session.set("skill_loader", components["skill_loader"])
        cl.user_session.set("registry", components["registry"])

        # LightRAG 初始化（异步）
        job_rag = components["job_rag"]
        try:
            await job_rag.initialize()
        except Exception as e:
            logger.warning("JobRAG 初始化失败: %s", e)
        cl.user_session.set("job_rag", job_rag)

        cl.user_session.set("agent_ready", True)
        cl.user_session.set("current_model", model)

        # 初始化 TaskMonitor（后台任务监控）
        from services.task_monitor import TaskMonitor, TaskNotification
        task_monitor = TaskMonitor()

        # 捕获当前 Chainlit context，后台 task 里需要恢复它才能发消息
        _cl_context = cl.context.session

        async def _ui_push(notif: TaskNotification) -> None:
            """当 agent 不在 loop 中时，直接推送通知到 UI"""
            try:
                from chainlit.context import init_ws_context
                init_ws_context(_cl_context)
                await cl.Message(
                    content=f"📋 {notif.message}\n\n需要我帮你同步数据并分析岗位吗？"
                ).send()
            except Exception as e:
                logger.warning("UI 推送失败: %s", e)

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
    """Chainlit 侧边栏点击历史对话时触发 — 恢复对话上下文并继续对话。"""
    config = load_config()
    cl.user_session.set("config", config)
    cl.user_session.set("chat_history", [])

    # 连接数据库
    db = Database(config.db_path)
    await db.connect()
    await db.init_schema()
    cl.user_session.set("db", db)

    chat_store = ChatHistoryStore()
    cl.user_session.set("chat_store", chat_store)
    trace_store = ExecutionTraceStore()
    cl.user_session.set("trace_store", trace_store)

    conv_id = thread.get("id")
    cl.user_session.set("conversation_id", conv_id)

    # 同步 .active 标记
    if conv_id:
        chat_store.set_active_conversation(conv_id)

    # 从 JSONL 恢复对话历史到内存
    restored = []
    if conv_id:
        restored = await chat_store.load_history(conv_id)
        if restored:
            history = [{"role": m["role"], "content": m["content"]} for m in restored if m.get("role") in ("user", "assistant", "system")]
            cl.user_session.set("chat_history", history)

    # 加载记忆画像
    memory_summary = ""
    try:
        cognitive_tool = GetUserCognitiveModelTool()
        result = await cognitive_tool.execute({}, {})
        memory_summary = result.get("summary", "")
    except Exception as e:
        logger.warning("加载记忆画像失败: %s", e)

    # Skills
    skills_section = ""

    # System prompt
    full_system_prompt = build_full_system_prompt(skills_prompt_section=skills_section)
    cl.user_session.set("system_prompt", full_system_prompt)

    # LLM 配置
    await _ensure_agent_ready(db, config)

    # Skills 重新生成
    skill_loader = cl.user_session.get("skill_loader")
    if skill_loader is not None:
        skills_section = skill_loader.to_prompt_section()
        full_system_prompt = build_full_system_prompt(skills_prompt_section=skills_section)
        cl.user_session.set("system_prompt", full_system_prompt)

    # 注入用户档案和记忆到对话历史
    if cl.user_session.get("agent_ready"):
        # --- 启动上一轮对话的记忆提取（如果有待处理的） ---
        pending_conv_id = cl.user_session.get("_pending_extract_conv_id")
        pending_messages = cl.user_session.get("_pending_extract_messages")
        if pending_conv_id and pending_messages:
            _launch_memory_extraction(pending_messages, pending_conv_id)
            cl.user_session.set("_pending_extract_conv_id", None)
            cl.user_session.set("_pending_extract_messages", None)

        profile_rows = await db.execute(
            "SELECT name, city, current_role, years_of_experience FROM resumes WHERE is_active = 1 LIMIT 1"
        )
        has_profile = bool(profile_rows and profile_rows[0].get("name"))
        history = cl.user_session.get("chat_history", [])
        if has_profile:
            profile_context = json.dumps(dict(profile_rows[0]), ensure_ascii=False, default=str)
            history.insert(0, {"role": "system", "content": f"[用户档案] {profile_context}"})
        if memory_summary:
            idx = 1 if has_profile else 0
            history.insert(idx, {"role": "system", "content": f"[用户记忆画像]\n{memory_summary}"})
        cl.user_session.set("chat_history", history)

        # 空对话（没有历史消息）时显示欢迎语
        has_history = any(m.get("role") in ("user", "assistant") for m in (restored or []))
        if not has_history:
            if has_profile:
                p = profile_rows[0]
                name = p.get("name", "")
                city = p.get("city", "")
                role = p.get("current_role", "")
                welcome = f"## 👋 欢迎回来，{name}\n\n"
                details = []
                if city:
                    details.append(f"📍 {city}")
                if role:
                    details.append(f"💼 {role}")
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


@cl.on_chat_start
async def on_chat_start():
    # 防止 WebSocket 重连导致重复执行
    if cl.user_session.get("_chat_started"):
        return
    cl.user_session.set("_chat_started", True)

    config = load_config()
    cl.user_session.set("config", config)
    cl.user_session.set("chat_history", [])
    cl.user_session.set("_conv_has_interaction", False)

    # 连接数据库
    db = Database(config.db_path)
    await db.connect()
    await db.init_schema()
    cl.user_session.set("db", db)

    # --- 初始化 ChatHistoryStore & ExecutionTraceStore ---
    chat_store = ChatHistoryStore()
    cl.user_session.set("chat_store", chat_store)
    trace_store = ExecutionTraceStore()
    cl.user_session.set("trace_store", trace_store)

    # --- 解析对话 ID ---
    # 优先读 .pending_new（前端新建对话时写入），读后立即删除
    pending_file = chat_store.base_dir / ".pending_new"
    pending_id: str | None = None
    if pending_file.exists():
        pending_id = pending_file.read_text(encoding="utf-8").strip() or None
        try:
            pending_file.unlink()
        except OSError:
            pass

    if pending_id:
        conv_id = pending_id
        conv_path = chat_store._conversation_path(conv_id)
        conv_path.parent.mkdir(parents=True, exist_ok=True)
        conv_path.touch(exist_ok=True)
        chat_store.set_active_conversation(conv_id)
    else:
        conv_id = await chat_store.get_active_conversation_id()
        if not conv_id:
            conv_id = await chat_store.create_conversation()

    # on_chat_start 永远不恢复旧消息到 UI。
    # 旧消息只通过 on_chat_resume（点击侧边栏历史对话）恢复。
    # 但仍然加载历史到 chat_history 内存（供 LLM 上下文使用）。
    restored_messages = []
    conv_path = chat_store._conversation_path(conv_id)
    if conv_path.exists() and conv_path.stat().st_size > 0:
        restored = await chat_store.load_history(conv_id)
        if restored:
            history = [{"role": m["role"], "content": m["content"]} for m in restored if m.get("role") in ("user", "assistant", "system")]
            cl.user_session.set("chat_history", history)

    cl.user_session.set("conversation_id", conv_id)

    # 同步 Chainlit 的 thread_id，让前端侧边栏能正确高亮当前对话
    try:
        cl.context.session.thread_id = conv_id
    except Exception:
        pass

    # --- 检查未提取记忆的历史对话 ---
    # 找最近一个有内容但未提取的对话，后台跑子 agent
    try:
        all_jsonl = sorted(chat_store.base_dir.glob("*.jsonl"))
        for jf in reversed(all_jsonl):
            cid = jf.stem
            if cid == conv_id:
                continue  # 跳过当前对话
            if chat_store.is_memory_extracted(cid):
                continue  # 已提取
            if jf.stat().st_size == 0:
                continue  # 空文件
            prev_messages = await chat_store.load_history(cid)
            has_content = any(m.get("role") in ("user", "assistant") for m in prev_messages)
            if has_content:
                logger.warning("🧠 对话 %s 未提取记忆，将在后台执行", cid)
                cl.user_session.set("_pending_extract_conv_id", cid)
                cl.user_session.set("_pending_extract_messages", prev_messages)
                break  # 一次只提取一个
    except Exception as e:
        logger.warning("检查历史对话记忆提取状态失败: %s", e)

    # --- 加载记忆画像摘要 ---
    memory_summary = ""
    try:
        cognitive_tool = GetUserCognitiveModelTool()
        result = await cognitive_tool.execute({}, {})
        memory_summary = result.get("summary", "")
    except Exception as e:
        logger.warning("加载记忆画像失败: %s", e)

    # --- 加载 Skills 摘要（在 Agent 初始化后从 bootstrap 的 skill_loader 获取） ---
    # 先用空 skills_section 构建 system prompt，Agent 初始化后再更新
    skills_section = ""

    # --- 构建完整 System Prompt（基础 + 记忆指引 + Skills） ---
    full_system_prompt = build_full_system_prompt(skills_prompt_section=skills_section)
    cl.user_session.set("system_prompt", full_system_prompt)

    # 尝试从数据库读取 LLM 配置
    await _ensure_agent_ready(db, config)

    # --- Agent 初始化后，用 bootstrap 的 skill_loader 重新生成 Skills 摘要 ---
    skill_loader = cl.user_session.get("skill_loader")
    if skill_loader is not None:
        skills_section = skill_loader.to_prompt_section()
        full_system_prompt = build_full_system_prompt(skills_prompt_section=skills_section)
        cl.user_session.set("system_prompt", full_system_prompt)

    if not cl.user_session.get("agent_ready"):
        # 未配置 — 固定欢迎语 + 引导配置
        await cl.Message(
            content="## 👋 你好，我是 MooBot\n\n"
            "我是你的 AI 求职顾问，可以帮你认识自己、搜索岗位、分析匹配度、准备面试。\n\n"
            "⚙️ 请先点击顶部导航栏的「设置」配置 API Key，保存后会自动回到对话。"
        ).send()
    else:
        # --- 启动上一轮对话的记忆提取（如果有待处理的） ---
        pending_conv_id = cl.user_session.get("_pending_extract_conv_id")
        pending_messages = cl.user_session.get("_pending_extract_messages")
        if pending_conv_id and pending_messages:
            _launch_memory_extraction(pending_messages, pending_conv_id)
            cl.user_session.set("_pending_extract_conv_id", None)
            cl.user_session.set("_pending_extract_messages", None)

        # 已配置 — 查用户档案，固定开场白 + 上下文注入
        profile_rows = await db.execute(
            "SELECT name, city, current_role, years_of_experience FROM resumes WHERE is_active = 1 LIMIT 1"
        )
        has_profile = bool(profile_rows and profile_rows[0].get("name"))

        if has_profile:
            p = profile_rows[0]
            name = p.get("name", "")
            city = p.get("city", "")
            role = p.get("current_role", "")
            welcome = f"## 👋 欢迎回来，{name}\n\n"
            details = []
            if city:
                details.append(f"📍 {city}")
            if role:
                details.append(f"💼 {role}")
            if details:
                welcome += " · ".join(details) + "\n\n"
            welcome += "有什么我可以帮你的？可以继续上次的求职进展，或者告诉我新的需求。"

            # 把用户档案摘要注入到对话历史的 system 上下文中
            history = cl.user_session.get("chat_history", [])
            profile_context = json.dumps(dict(profile_rows[0]), ensure_ascii=False, default=str)
            history.insert(0, {
                "role": "system",
                "content": f"[用户档案] {profile_context}",
            })
            # 注入记忆画像摘要到 system 上下文
            if memory_summary:
                history.insert(1, {
                    "role": "system",
                    "content": f"[用户记忆画像]\n{memory_summary}",
                })
            cl.user_session.set("chat_history", history)
        else:
            # 无档案时也注入记忆画像（如果有）
            if memory_summary:
                history = cl.user_session.get("chat_history", [])
                history.insert(0, {
                    "role": "system",
                    "content": f"[用户记忆画像]\n{memory_summary}",
                })
                cl.user_session.set("chat_history", history)

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
    import time as _time
    payload = action.payload or {}
    card_type = payload.get("card_type", "unknown")
    params = payload.get("params", {})
    job_ids = payload.get("job_ids", [])

    card_el = cl.user_session.get(f"action_card_{card_type}")
    if card_el:
        card_el.props["status"] = "executing"
        await card_el.update()

    if card_type == "start_task":
        await _execute_start_task(params, card_el)
    elif card_type == "fetch_detail":
        await _execute_fetch_detail(params, job_ids, card_el)
    elif card_type == "deliver":
        await _execute_deliver(params, job_ids, card_el)
    else:
        if card_el:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = f"未知操作类型: {card_type}"
            await card_el.update()


async def _execute_start_task(params: dict, card_el):
    """执行爬取：update_config → start_task → 后台轮询 → 推送任务面板"""
    import time as _time
    import json as _json
    getjob_client = cl.user_session.get("getjob_client")
    if not getjob_client:
        if card_el:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = "getjob 服务未配置"
            await card_el.update()
        return

    platform = "liepin"
    config_data = {k: params[k] for k in ("keywords", "city", "salaryCode", "workYearCode", "eduLevel", "maxPages", "maxItems") if k in params and params[k] not in (None, "")}
    config_data["scrapeOnly"] = True

    if config_data:
        await getjob_client.update_config(platform, config_data)

    result = await getjob_client.start_task(platform)
    if not result.get("success"):
        if card_el:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = result.get("error", "启动失败")
            await card_el.update()
        return

    if card_el:
        card_el.props["status"] = "completed"
        card_el.props["result_message"] = "爬取任务已启动！进度请看右侧面板 →"
        await card_el.update()

    task_monitor = cl.user_session.get("task_monitor")
    if task_monitor:
        task_id = f"{platform}-{int(_time.time())}"
        db = cl.user_session.get("db")

        async def _on_complete(p: str) -> dict:
            from tools.getjob.platform_sync import SyncJobsTool
            if not db:
                return {}
            return await SyncJobsTool().execute({"platform": p}, {"db": db, "getjob_client": getjob_client})

        task_monitor.start_polling(
            task_id=task_id, platform=platform, client=getjob_client,
            on_complete=_on_complete,
            agent_busy_check=lambda: cl.user_session.get("agent_busy", False),
        )

    await cl.send_window_message(_json.dumps({
        "type": "task_panel_update",
        "tasks": [{"task_id": f"{platform}-{int(_time.time())}", "name": "爬取岗位列表", "platform": platform, "status": "running", "progress_text": "启动中...", "elapsed_s": 0}],
    }))


async def _execute_fetch_detail(params: dict, job_ids: list, card_el):
    """执行批量获取岗位详情"""
    if not job_ids:
        if card_el:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = "未选择岗位"
            await card_el.update()
        return

    from tools.getjob.fetch_detail import FetchJobDetailTool
    db = cl.user_session.get("db")
    result = await FetchJobDetailTool().execute(
        {"job_ids": job_ids, "force": params.get("force", False)},
        {"db": db, "getjob_client": cl.user_session.get("getjob_client"), "job_rag": cl.user_session.get("job_rag")},
    )
    if card_el:
        if result.get("success"):
            card_el.props["status"] = "completed"
            card_el.props["result_message"] = f"完成：获取 {result.get('fetched', 0)} 条，跳过 {result.get('skipped', 0)} 条"
        else:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = result.get("error", "获取失败")
        await card_el.update()


async def _execute_deliver(params: dict, job_ids: list, card_el):
    """执行投递打招呼"""
    if not job_ids:
        if card_el:
            card_el.props["status"] = "failed"
            card_el.props["result_message"] = "未选择岗位"
            await card_el.update()
        return

    from tools.getjob.platform_deliver import PlatformDeliverTool
    result = await PlatformDeliverTool().execute(
        {"platform": "liepin", "job_ids": job_ids},
        {"getjob_client": cl.user_session.get("getjob_client")},
    )
    if card_el:
        if result.get("success"):
            card_el.props["status"] = "completed"
            card_el.props["result_message"] = "投递完成！"
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

    # --- 持久化用户消息到 JSONL ---
    chat_store: ChatHistoryStore | None = cl.user_session.get("chat_store")
    conv_id: str | None = cl.user_session.get("conversation_id")
    if chat_store and conv_id:
        try:
            await chat_store.save_message(conv_id, "user", content)
        except Exception as e:
            logger.warning("持久化用户消息失败: %s", e)

    executor = cl.user_session.get("executor")
    system_prompt = cl.user_session.get("system_prompt")

    # 用对话历史直接调 Executor.chat()
    # LLM 自己决定是纯回复、调工具、还是两者同时
    current_step: cl.Step | None = None
    assistant_text = ""
    pending_elements: list = []  # 攒着，等 AI 回复后再发
    db = cl.user_session.get("db")

    # --- 执行轨迹收集 ---
    trace_events: list[dict] = []
    trace_started_at = datetime.now()

    # --- 对话日志 ---
    conv_logger: ConversationLogger | None = None
    if conv_id:
        conv_logger = ConversationLogger(conv_id)
        conv_logger.begin_turn(content)

    # 标记 agent 正在处理中（后台任务通知会据此判断是否直接推送 UI）
    cl.user_session.set("agent_busy", True)

    async for event in executor.chat(messages=history, context={"db": db, "llm_client": executor._llm, "getjob_client": cl.user_session.get("getjob_client"), "task_monitor": cl.user_session.get("task_monitor"), "agent_busy_check": lambda: cl.user_session.get("agent_busy", False), "conversation_logger": conv_logger, "job_rag": cl.user_session.get("job_rag")}, system_prompt=system_prompt):
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
            pending_elements.append(element)

        elif event.type == "ui_render":
            tool_name = event.data.get("tool_name", "")
            for_ui = event.data.get("for_ui", {})

            if tool_name == "query_jobs" and for_ui.get("jobs"):
                id_map = {}
                for j in for_ui["jobs"]:
                    id_map[j["seq"]] = {"id": j["id"], "title": j["title"], "company": j["company"]}
                cl.user_session.set("job_id_map", id_map)

                element = cl.CustomElement(name="JobList", props=for_ui, display="inline")
                pending_elements.append(element)

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
            # 后台任务完成通知 — 展示给用户
            notif_msg = event.data.get("message", "")
            platform = event.data.get("platform", "")
            status = event.data.get("status", "")
            if status == "completed":
                await cl.Message(content=f"📋 {notif_msg}").send()
            elif status == "timeout":
                await cl.Message(content=f"⏰ {notif_msg}").send()
            else:
                await cl.Message(content=f"ℹ️ {notif_msg}").send()

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

        # --- 持久化 assistant 回复到 JSONL ---
        if chat_store and conv_id:
            try:
                await chat_store.save_message(conv_id, "assistant", assistant_text)
            except Exception as e:
                logger.warning("持久化 assistant 消息失败: %s", e)

    # --- 结束对话日志轮次 ---
    if conv_logger:
        conv_logger.end_turn(assistant_text or "(no reply)")

    # --- 持久化执行轨迹 ---
    trace_store: ExecutionTraceStore | None = cl.user_session.get("trace_store")
    if trace_store and conv_id and trace_events:
        try:
            trace_store.save_trace(
                conversation_id=conv_id,
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

        # 获取 chat_store 用于标记提取完成
        chat_store: ChatHistoryStore | None = cl.user_session.get("chat_store")

        logger.info("🧠 启动记忆提取任务，对话 %s，消息数: %d", conversation_id, len(messages))
        asyncio.create_task(_run_extraction(extractor, messages, context, chat_store, conversation_id))
    except Exception as e:
        logger.error("🧠 启动记忆提取失败: %s", e, exc_info=True)


async def _run_extraction(
    extractor,
    messages: list[dict],
    context: dict,
    chat_store: ChatHistoryStore | None = None,
    conversation_id: str | None = None,
) -> None:
    """运行记忆提取，完成后标记 .extracted，捕获所有异常。"""
    try:
        logger.info("🧠 开始记忆提取，消息数: %d, 会话: %s", len(messages), context.get("conversation_id", "?"))
        await extractor.extract(messages, context)
        # 标记提取完成
        if chat_store and conversation_id:
            chat_store.mark_memory_extracted(conversation_id)
        logger.info("🧠 记忆提取完成，已标记 %s", conversation_id)
    except Exception as e:
        logger.error("🧠 记忆提取执行失败: %s", e, exc_info=True)
