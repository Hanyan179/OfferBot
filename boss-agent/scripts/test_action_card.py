"""
ActionCard 组件测试页面。

用法：
  cd boss-agent
  chainlit run scripts/test_action_card.py -w --port 7861

命令：
  start_task    — 启动爬取卡片（猎聘参数完整版）
  fetch_detail  — 批量抓详情卡片（带岗位选择列表）
  deliver       — 投递打招呼卡片（带岗位选择列表）
  update_config — 更新配置卡片
  all           — 显示所有卡片
"""

import json
import chainlit as cl

# ---- 猎聘城市选项 ----
CITY_OPTIONS = [
    {"value": "全国", "label": "全国"},
    {"value": "北京", "label": "北京"},
    {"value": "上海", "label": "上海"},
    {"value": "深圳", "label": "深圳"},
    {"value": "广州", "label": "广州"},
    {"value": "杭州", "label": "杭州"},
    {"value": "成都", "label": "成都"},
    {"value": "南京", "label": "南京"},
    {"value": "苏州", "label": "苏州"},
    {"value": "武汉", "label": "武汉"},
]

SALARY_OPTIONS = [
    {"value": "1", "label": "10万以下"},
    {"value": "2", "label": "10-15万"},
    {"value": "3", "label": "15-20万"},
    {"value": "4", "label": "20-30万"},
    {"value": "5", "label": "30-50万"},
    {"value": "6", "label": "50-100万"},
    {"value": "7", "label": "100万以上"},
]

# ---- Mock 岗位数据 ----
MOCK_JOBS = [
    {"id": 101, "title": "AI Agent 工程师", "company": "字节跳动", "salary": "40-60K", "city": "上海", "has_jd": True},
    {"id": 102, "title": "LLM 应用开发", "company": "阿里巴巴", "salary": "35-50K", "city": "杭州", "has_jd": False},
    {"id": 103, "title": "全栈工程师(AI方向)", "company": "美团", "salary": "30-45K", "city": "北京", "has_jd": False},
    {"id": 104, "title": "AI 平台架构师", "company": "腾讯", "salary": "50-80K", "city": "深圳", "has_jd": True},
    {"id": 105, "title": "RAG 系统工程师", "company": "百度", "salary": "35-55K", "city": "北京", "has_jd": False},
    {"id": 106, "title": "AI 产品工程师", "company": "蚂蚁集团", "salary": "40-60K", "city": "杭州", "has_jd": False},
    {"id": 107, "title": "大模型应用开发", "company": "京东", "salary": "30-50K", "city": "北京", "has_jd": False},
]

# ---- Mock 卡片数据 ----
MOCK_CARDS = {
    "start_task": {
        "card_type": "start_task",
        "title": "🚀 启动岗位爬取",
        "description": "将在猎聘平台搜索以下条件的岗位（仅爬取，不投递）",
        "fields": [
            {"id": "keywords", "label": "搜索关键词", "type": "text", "value": "AI Agent工程师,全栈开发", "required": True},
            {"id": "city", "label": "城市", "type": "select", "options": CITY_OPTIONS, "value": "上海"},
            {"id": "salaryCode", "label": "薪资范围", "type": "select", "options": SALARY_OPTIONS, "value": "5"},
            {"id": "maxPages", "label": "最大页数", "type": "number", "value": 3},
            {"id": "maxItems", "label": "最大岗位数", "type": "number", "value": 100},
        ],
        "status": "pending",
    },
    "fetch_detail": {
        "card_type": "fetch_detail",
        "title": "📄 批量获取岗位详情",
        "description": "将爬取选中岗位的完整 JD（已有 JD 的会跳过）",
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
        "jobs": [j for j in MOCK_JOBS if j["has_jd"]],  # 只展示有 JD 的
        "status": "pending",
    },
    "update_config": {
        "card_type": "update_config",
        "title": "⚙️ 更新搜索配置",
        "description": "修改猎聘搜索配置（下次爬取生效）",
        "fields": [
            {"id": "keywords", "label": "搜索关键词", "type": "text", "value": "AI Agent,LLM工程师"},
            {"id": "city", "label": "城市", "type": "select", "options": CITY_OPTIONS, "value": "上海"},
            {"id": "salaryCode", "label": "薪资范围", "type": "select", "options": SALARY_OPTIONS, "value": "5"},
            {"id": "maxPages", "label": "最大页数", "type": "number", "value": 10},
            {"id": "maxItems", "label": "最大岗位数", "type": "number", "value": 500},
        ],
        "status": "pending",
    },
}


@cl.on_chat_start
async def on_start():
    await cl.Message(
        content=(
            "🧪 **ActionCard 测试页面**\n\n"
            "输入命令测试不同卡片：\n"
            "- `start_task` — 启动爬取（猎聘完整参数）\n"
            "- `fetch_detail` — 批量抓详情（带岗位选择列表）\n"
            "- `deliver` — 投递打招呼（带岗位选择列表）\n"
            "- `update_config` — 更新配置\n"
            "- `all` — 显示所有卡片"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    text = message.content.strip().lower()

    if text == "all":
        for key, card_data in MOCK_CARDS.items():
            element = cl.CustomElement(name="ActionCard", props=card_data, display="inline")
            cl.user_session.set(f"card_{key}", element)
            await cl.Message(content=f"AI 建议执行以下操作：", elements=[element]).send()
        return

    if text in MOCK_CARDS:
        card_data = MOCK_CARDS[text]
        element = cl.CustomElement(name="ActionCard", props=card_data, display="inline")
        cl.user_session.set(f"card_{text}", element)
        await cl.Message(content="AI 建议执行以下操作：", elements=[element]).send()
        return

    await cl.Message(content=f"未知命令: `{text}`\n\n可用: start_task / fetch_detail / deliver / update_config / all").send()


@cl.action_callback("action_card_submit")
async def on_action_submit(action: cl.Action):
    payload = action.payload or {}
    card_type = payload.get("card_type", "unknown")
    params = payload.get("params", {})
    job_ids = payload.get("job_ids", [])

    parts = [f"✅ 用户确认执行 **{card_type}**\n"]
    if params:
        parts.append(f"参数：\n```json\n{json.dumps(params, ensure_ascii=False, indent=2)}\n```")
    if job_ids:
        parts.append(f"选中岗位 ID: {job_ids}")
    parts.append(f"\n（实际场景：POST `/api/actions/{card_type}` 执行）")

    await cl.Message(content="\n".join(parts)).send()

    # 模拟更新卡片状态
    element = cl.user_session.get(f"card_{card_type}")
    if element:
        element.props["status"] = "completed"
        element.props["result_message"] = f"模拟执行成功！"
        await element.update()


@cl.action_callback("action_card_cancel")
async def on_action_cancel(action: cl.Action):
    card_type = (action.payload or {}).get("card_type", "unknown")
    await cl.Message(content=f"❌ 用户取消了 **{card_type}** 操作").send()
