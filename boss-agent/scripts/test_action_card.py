"""
ActionCard + TaskPanel 组件测试页面。

用法：
  cd boss-agent
  chainlit run scripts/test_action_card.py -w --port 7861

命令：
  start_task    — 启动爬取卡片
  fetch_detail  — 批量抓详情卡片
  deliver       — 投递打招呼卡片
  all           — 显示所有卡片
  tasks         — 显示任务面板（mock 数据）
  tasks_live    — 显示任务面板（轮询真实 /api/tasks）
"""

import json
import asyncio
import chainlit as cl

# ---- 猎聘选项 ----

CITY_OPTIONS = [
    {"value": "全国", "label": "全国"}, {"value": "北京", "label": "北京"},
    {"value": "上海", "label": "上海"}, {"value": "天津", "label": "天津"},
    {"value": "重庆", "label": "重庆"}, {"value": "广州", "label": "广州"},
    {"value": "深圳", "label": "深圳"}, {"value": "苏州", "label": "苏州"},
    {"value": "南京", "label": "南京"}, {"value": "杭州", "label": "杭州"},
    {"value": "大连", "label": "大连"}, {"value": "成都", "label": "成都"},
    {"value": "武汉", "label": "武汉"}, {"value": "西安", "label": "西安"},
]
SALARY_OPTIONS = [
    {"value": "1", "label": "10万以下"}, {"value": "2", "label": "10-15万"},
    {"value": "3", "label": "15-20万"}, {"value": "4", "label": "20-30万"},
    {"value": "5", "label": "30-50万"}, {"value": "6", "label": "50-100万"},
    {"value": "7", "label": "100万以上"},
]
WORK_YEAR_OPTIONS = [
    {"value": "0", "label": "不限"}, {"value": "1$3", "label": "1-3年"},
    {"value": "3$5", "label": "3-5年"}, {"value": "5$10", "label": "5-10年"},
    {"value": "10$99", "label": "10年以上"},
]
EDU_OPTIONS = [
    {"value": "000", "label": "不限"}, {"value": "030", "label": "大专"},
    {"value": "040", "label": "本科"}, {"value": "050", "label": "硕士"},
    {"value": "060", "label": "博士"},
]

# ---- Mock 岗位 ----
MOCK_JOBS = [
    {"id": 101, "title": "AI Agent 工程师", "company": "字节跳动", "salary": "40-60K", "city": "上海", "has_jd": True},
    {"id": 102, "title": "LLM 应用开发", "company": "阿里巴巴", "salary": "35-50K", "city": "杭州", "has_jd": False},
    {"id": 103, "title": "全栈工程师(AI方向)", "company": "美团", "salary": "30-45K", "city": "北京", "has_jd": False},
    {"id": 104, "title": "AI 平台架构师", "company": "腾讯", "salary": "50-80K", "city": "深圳", "has_jd": True},
    {"id": 105, "title": "RAG 系统工程师", "company": "百度", "salary": "35-55K", "city": "北京", "has_jd": False},
    {"id": 106, "title": "AI 产品工程师", "company": "蚂蚁集团", "salary": "40-60K", "city": "杭州", "has_jd": False},
    {"id": 107, "title": "大模型应用开发", "company": "京东", "salary": "30-50K", "city": "北京", "has_jd": False},
]

# ---- 卡片定义 ----
MOCK_CARDS = {
    "start_task": {
        "card_type": "start_task",
        "title": "🚀 启动岗位爬取",
        "description": "将在猎聘平台搜索以下条件的岗位（仅爬取，不投递）",
        "fields": [
            {"id": "keywords", "label": "搜索关键词", "type": "text", "value": "AI Agent工程师,全栈开发", "required": True},
            {"id": "city", "label": "城市", "type": "select", "options": CITY_OPTIONS, "value": "上海"},
            {"id": "salaryCode", "label": "薪资范围", "type": "select", "options": SALARY_OPTIONS, "value": "5"},
            {"id": "workYearCode", "label": "工作年限", "type": "select", "options": WORK_YEAR_OPTIONS, "value": "3$5"},
            {"id": "eduLevel", "label": "学历要求", "type": "select", "options": EDU_OPTIONS, "value": "040"},
            {"id": "maxPages", "label": "最大页数", "type": "number", "value": 3},
            {"id": "maxItems", "label": "最大岗位数", "type": "number", "value": 100},
        ],
        "status": "pending",
    },
    "fetch_detail": {
        "card_type": "fetch_detail",
        "title": "📄 批量获取岗位详情",
        "description": "将爬取选中岗位的完整 JD（已有 JD 的会自动跳过）",
        "fields": [
            {"id": "force", "label": "强制重新获取", "type": "switch", "value": False},
        ],
        "jobs": MOCK_JOBS,
        "status": "pending",
    },
    "deliver": {
        "card_type": "deliver",
        "title": "📨 投递打招呼",
        "description": "将对选中岗位执行投递（需要已登录猎聘）",
        "fields": [],
        "jobs": [j for j in MOCK_JOBS if j["has_jd"]],
        "status": "pending",
    },
}

# ---- Mock 任务数据 ----
MOCK_TASKS = [
    {
        "task_id": "liepin-1712548800",
        "name": "爬取岗位列表",
        "platform": "liepin",
        "status": "running",
        "progress_text": "32/100",
        "elapsed_s": 45,
        "started_at": "2026-04-08T11:00:00",
        "finished_at": None,
    },
    {
        "task_id": "fetch-detail-1712548900",
        "name": "爬取岗位详情（5条）",
        "platform": "liepin",
        "status": "running",
        "progress_text": "2/5 成功2 失败0",
        "elapsed_s": 120,
        "started_at": "2026-04-08T10:58:00",
        "finished_at": None,
    },
    {
        "task_id": "rag-insert-1712549000",
        "name": "知识图谱化（3条）",
        "platform": "rag",
        "status": "completed",
        "progress_text": "3/3",
        "elapsed_s": 72,
        "started_at": "2026-04-08T10:55:00",
        "finished_at": "2026-04-08T10:56:12",
    },
    {
        "task_id": "deliver-1712549100",
        "name": "投递打招呼（2条）",
        "platform": "liepin",
        "status": "failed",
        "progress_text": "登录已过期",
        "elapsed_s": 8,
        "started_at": "2026-04-08T10:50:00",
        "finished_at": "2026-04-08T10:50:08",
    },
]


@cl.on_chat_start
async def on_start():
    await cl.Message(
        content=(
            "🧪 **ActionCard + TaskPanel 测试页面**\n\n"
            "操作卡片：\n"
            "- `start_task` / `fetch_detail` / `deliver` / `all`\n\n"
            "任务面板：\n"
            "- `tasks` — mock 数据\n"
            "- `tasks_live` — 轮询真实 /api/tasks（需要主服务在 7860 运行）\n\n"
            "模拟流程：\n"
            "- `demo` — 完整流程：卡片确认 → 任务面板出现进度"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    text = message.content.strip().lower()

    if text == "all":
        for key, card_data in MOCK_CARDS.items():
            element = cl.CustomElement(name="ActionCard", props=card_data, display="inline")
            cl.user_session.set(f"card_{key}", element)
            await cl.Message(content="AI 建议执行以下操作：", elements=[element]).send()
        return

    if text in MOCK_CARDS:
        card_data = MOCK_CARDS[text]
        element = cl.CustomElement(name="ActionCard", props=card_data, display="inline")
        cl.user_session.set(f"card_{text}", element)
        await cl.Message(content="AI 建议执行以下操作：", elements=[element]).send()
        return

    if text == "tasks":
        element = cl.CustomElement(name="TaskPanel", props={"tasks": MOCK_TASKS}, display="inline")
        cl.user_session.set("task_panel", element)
        await cl.Message(content="当前任务状态：", elements=[element]).send()
        return

    if text == "tasks_live":
        element = cl.CustomElement(name="TaskPanel", props={"tasks": [], "poll_url": "http://localhost:7860/api/tasks"}, display="inline")
        cl.user_session.set("task_panel", element)
        await cl.Message(content="任务面板（实时轮询）：", elements=[element]).send()
        return

    if text == "demo":
        await _run_demo()
        return

    await cl.Message(content=f"未知命令: `{text}`\n\n可用: start_task / fetch_detail / deliver / all / tasks / tasks_live / demo").send()


async def _run_demo():
    """模拟完整流程：显示爬取卡片 → 用户确认 → 任务面板出现进度 → 完成"""
    # 1. 显示爬取卡片
    card = cl.CustomElement(name="ActionCard", props=MOCK_CARDS["start_task"], display="inline")
    cl.user_session.set("card_start_task", card)
    await cl.Message(content="AI 分析了你的需求，建议执行以下操作：", elements=[card]).send()

    # 2. 同时显示空任务面板
    panel = cl.CustomElement(name="TaskPanel", props={"tasks": []}, display="inline")
    cl.user_session.set("task_panel", panel)
    await cl.Message(content="任务面板：", elements=[panel]).send()

    await cl.Message(content="💡 点击卡片上的「执行」按钮，任务面板会模拟显示进度。").send()


@cl.action_callback("action_card_submit")
async def on_action_submit(action: cl.Action):
    payload = action.payload or {}
    card_type = payload.get("card_type", "unknown")
    params = payload.get("params", {})
    job_ids = payload.get("job_ids", [])

    parts = [f"✅ 用户确认执行 **{card_type}**"]
    if params:
        parts.append(f"```json\n{json.dumps(params, ensure_ascii=False, indent=2)}\n```")
    if job_ids:
        parts.append(f"选中岗位: {len(job_ids)} 个")
    await cl.Message(content="\n".join(parts)).send()

    # 更新卡片状态
    card_el = cl.user_session.get(f"card_{card_type}")
    if card_el:
        card_el.props["status"] = "executing"
        await card_el.update()

    # 模拟任务进度
    panel_el = cl.user_session.get("task_panel")
    if panel_el:
        task = {
            "task_id": f"{card_type}-demo",
            "name": {"start_task": "爬取岗位列表", "fetch_detail": f"爬取岗位详情（{len(job_ids)}条）", "deliver": f"投递打招呼（{len(job_ids)}条）"}.get(card_type, card_type),
            "platform": "liepin",
            "status": "running",
            "progress_text": "0/100",
            "elapsed_s": 0,
        }
        panel_el.props["tasks"] = [task] + (panel_el.props.get("tasks") or [])
        await panel_el.update()

        # 模拟进度推进
        for i in range(1, 6):
            await asyncio.sleep(1)
            task["progress_text"] = f"{i * 20}/100"
            task["elapsed_s"] = i
            panel_el.props["tasks"] = [task] + [t for t in (panel_el.props.get("tasks") or []) if t["task_id"] != task["task_id"]]
            await panel_el.update()

        # 完成
        task["status"] = "completed"
        task["progress_text"] = "100/100"
        task["elapsed_s"] = 5
        panel_el.props["tasks"] = [task] + [t for t in (panel_el.props.get("tasks") or []) if t["task_id"] != task["task_id"]]
        await panel_el.update()

    # 更新卡片为完成
    if card_el:
        card_el.props["status"] = "completed"
        card_el.props["result_message"] = "执行完成！"
        await card_el.update()

    await cl.Message(content="✅ 任务已完成，数据已同步到本地。").send()


@cl.action_callback("action_card_cancel")
async def on_action_cancel(action: cl.Action):
    card_type = (action.payload or {}).get("card_type", "unknown")
    await cl.Message(content=f"❌ 用户取消了 **{card_type}** 操作").send()


@cl.action_callback("task_panel_stop")
async def on_task_stop(action: cl.Action):
    payload = action.payload or {}
    task_id = payload.get("task_id", "")
    await cl.Message(content=f"⏹ 停止任务: {task_id}").send()

    panel_el = cl.user_session.get("task_panel")
    if panel_el and panel_el.props.get("tasks"):
        for t in panel_el.props["tasks"]:
            if t["task_id"] == task_id:
                t["status"] = "failed"
                t["progress_text"] = "已停止"
        await panel_el.update()
