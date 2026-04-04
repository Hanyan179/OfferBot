"""
Chainlit 对话逻辑（挂载到 /chat）

接入 Agent Core：用户消息 → Planner → Executor → Step 展示工具调用
LLM 配置从 /settings 页面管理，保存在 SQLite user_preferences 表中。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import chainlit as cl

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config import load_config
from db.database import Database
from agent.bootstrap import bootstrap

SCENARIO_CARDS: list[dict[str, str]] = [
    {"emoji": "🔍", "title": "搜索岗位", "prompt": "帮我搜索上海 AI 岗位"},
    {"emoji": "📊", "title": "简历匹配", "prompt": "分析我的简历匹配度"},
    {"emoji": "👋", "title": "打招呼语", "prompt": "生成打招呼语"},
    {"emoji": "📈", "title": "投递统计", "prompt": "查看投递统计"},
]

# 厂商预设（和 app.py 保持一致）
PROVIDER_PRESETS = {
    "dashscope": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.5-flash"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": "gemini-2.5-flash"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
}


async def _load_llm_config(db: Database) -> dict | None:
    """从数据库读取 LLM 配置，返回 {api_key, base_url, model} 或 None。"""
    keys = ("llm_provider", "llm_api_key", "llm_base_url", "llm_model")
    result = {}
    for key in keys:
        rows = await db.execute("SELECT value FROM user_preferences WHERE key = ?", (key,))
        result[key] = rows[0]["value"] if rows else ""

    api_key = result.get("llm_api_key", "")
    if not api_key:
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
        cl.user_session.set("agent_ready", True)
        cl.user_session.set("current_model", model)
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


@cl.on_chat_start
async def on_chat_start():
    config = load_config()
    cl.user_session.set("config", config)
    cl.user_session.set("chat_history", [])

    # 连接数据库
    db = Database(config.db_path)
    await db.connect()
    await db.init_schema()
    cl.user_session.set("db", db)

    # 尝试从数据库读取 LLM 配置
    llm_config = await _load_llm_config(db)

    # 如果数据库没有，尝试环境变量
    if llm_config is None and config.dashscope_api_key:
        llm_config = {
            "api_key": config.dashscope_api_key,
            "base_url": config.api_base_url,
            "model": config.dashscope_llm_model,
        }

    if llm_config:
        await _init_agent(db, **llm_config)
    else:
        cl.user_session.set("agent_ready", False)

    if not cl.user_session.get("agent_ready"):
        # 未配置 — 固定欢迎语 + 引导配置
        await cl.Message(
            content="## 👋 你好，我是 OfferBot\n\n"
            "我是你的 AI 求职顾问，可以帮你认识自己、搜索岗位、分析匹配度、准备面试。\n\n"
            "⚙️ 请先点击顶部导航栏的「设置」配置 API Key，保存后会自动回到对话。"
        ).send()
    else:
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
            cl.user_session.set("chat_history", history)
        else:
            welcome = (
                "## 👋 你好，我是 OfferBot\n\n"
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
        await cl.Message(
            content="⚠️ Agent 未就绪，请先在顶部导航栏点击「⚙️ 设置」配置 API Key。"
        ).send()
        return

    executor = cl.user_session.get("executor")

    # 用对话历史直接调 Executor.chat()
    # LLM 自己决定是纯回复、调工具、还是两者同时
    current_step: cl.Step | None = None
    assistant_text = ""
    db = cl.user_session.get("db")

    async for event in executor.chat(messages=history, context={"db": db}):
        if event.type == "thinking":
            # 思考过程 — 折叠展示
            thinking_text = event.data.get("content", "")
            if thinking_text:
                async with cl.Step(name="💭 思考中", type="llm") as think_step:
                    think_step.output = thinking_text

        elif event.type == "assistant_message":
            # LLM 的文本回复 — 直接展示给用户
            text = event.data.get("content", "")
            if text:
                assistant_text = text
                await cl.Message(content=text).send()

        elif event.type == "tool_start":
            tool_name = event.data.get("tool_name", "unknown")
            tool_args = event.data.get("arguments", {})
            current_step = cl.Step(name=f"🔧 {tool_name}", type="tool")
            current_step.input = json.dumps(tool_args, ensure_ascii=False, indent=2) if tool_args else "(无参数)"
            await current_step.__aenter__()

        elif event.type == "tool_result":
            success = event.data.get("success", False)
            data = event.data.get("data", {})

            if current_step is not None:
                if success:
                    current_step.output = _format_tool_result(data)
                else:
                    current_step.output = "❌ 执行失败"
                await current_step.__aexit__(None, None, None)
                current_step = None

        elif event.type == "error":
            error_text = event.data.get("message", "")
            await cl.Message(content=f"❌ {error_text}").send()
            if current_step is not None:
                current_step.output = f"错误: {error_text}"
                await current_step.__aexit__(None, None, None)
                current_step = None

        elif event.type == "max_turns_reached":
            await cl.Message(content="⚠️ 达到最大工具调用轮数，已停止。").send()

    # 记录 assistant 回复到历史
    if assistant_text:
        history.append({"role": "assistant", "content": assistant_text})
    cl.user_session.set("chat_history", history)
