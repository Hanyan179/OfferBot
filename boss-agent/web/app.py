"""
Boss Agent — FastAPI 主应用（单页面架构）

- / → 单页面入口（导航 + 标签页切换）
- /chat → Chainlit 对话（iframe 嵌入）
- /page/settings → 设置面板（iframe 嵌入）
- /page/jobs, /page/resume 等 → 各功能面板（iframe 嵌入）
- /api/settings → 设置 API
"""

from __future__ import annotations

import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

from chainlit.utils import mount_chainlit
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config import load_config
from db.database import Database

app = FastAPI(title="Boss Agent")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

PROVIDER_PRESETS = {
    "dashscope": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.6-plus"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": "gemini-3.1-flash-lite-preview"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "custom": {"base_url": "", "model": ""},
}


async def _get_db() -> Database:
    if not hasattr(app.state, "db") or app.state.db is None:
        config = load_config()
        db = Database(config.db_path)
        await db.connect()
        await db.init_schema()
        app.state.db = db
    return app.state.db


async def _load_llm_settings(db: Database) -> dict:
    keys = ("llm_provider", "llm_api_key", "llm_base_url", "llm_model")
    result = {}
    for key in keys:
        rows = await db.execute("SELECT value FROM user_preferences WHERE key = ?", (key,))
        result[key] = rows[0]["value"] if rows else ""
    return result


async def _save_llm_settings(db: Database, provider: str, api_key: str, base_url: str, model: str) -> None:
    pairs = [("llm_provider", provider), ("llm_api_key", api_key), ("llm_base_url", base_url), ("llm_model", model)]
    for key, value in pairs:
        await db.execute_write(
            "INSERT INTO user_preferences (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (key, value),
        )


def _safe_json_load(val: str | None) -> list | dict | None:
    """Safely parse a JSON string, returning None on failure."""
    if not val:
        return None
    try:
        import json
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None


async def _load_active_resume(db: Database) -> dict:
    """Load the active resume from SQLite and transform it for the template."""
    rows = await db.execute(
        "SELECT * FROM resumes WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
    )
    empty = {
        "name": None, "city": None, "experience": None, "education": None,
        "school": None, "major": None, "current_company": None, "current_role": None,
        "summary": None, "self_evaluation": None,
        "tech_stack": [], "tech_stack_grouped": {},
        "work_experience": [], "projects": [], "highlights": [],
        "job_preferences": None,
    }
    if not rows:
        return empty

    row = rows[0]
    years = row.get("years_of_experience")
    experience_str = f"{years}年" if years is not None else row.get("current_role")

    # Parse JSON fields
    skills_flat = _safe_json_load(row.get("skills_flat")) or []
    tech_stack_dict = _safe_json_load(row.get("tech_stack"))
    tech_stack_grouped = tech_stack_dict if isinstance(tech_stack_dict, dict) else {}
    if isinstance(tech_stack_dict, dict):
        tech_list = []
        for skills in tech_stack_dict.values():
            if isinstance(skills, list):
                tech_list.extend(skills)
        tech_stack = tech_list if tech_list else skills_flat
    else:
        tech_stack = skills_flat

    work_exp_raw = _safe_json_load(row.get("work_experience")) or []
    work_experience = []
    for exp in work_exp_raw:
        if isinstance(exp, dict):
            work_experience.append({
                "company": exp.get("company", ""),
                "role": exp.get("role", ""),
                "duration": exp.get("duration", ""),
                "description": exp.get("description", ""),
                "highlights": exp.get("highlights", []),
                "tech_stack": exp.get("tech_stack", ""),
            })

    projects_raw = _safe_json_load(row.get("projects")) or []
    projects = []
    for proj in projects_raw:
        if isinstance(proj, dict):
            projects.append({
                "name": proj.get("name", ""),
                "description": proj.get("description", ""),
                "tech_stack": proj.get("tech_stack", ""),
                "highlights": proj.get("highlights", []),
            })

    highlights = _safe_json_load(row.get("highlights")) or []

    # 求职意向
    resume_id = row.get("id")
    job_preferences = None
    if resume_id:
        pref_rows = await db.execute(
            "SELECT * FROM job_preferences WHERE resume_id = ? AND is_active = 1 LIMIT 1",
            (resume_id,),
        )
        if pref_rows:
            p = pref_rows[0]
            target_cities = _safe_json_load(p.get("target_cities")) or []
            target_roles = _safe_json_load(p.get("target_roles")) or []
            priorities = _safe_json_load(p.get("priorities")) or []
            deal_breakers = _safe_json_load(p.get("deal_breakers")) or []
            job_preferences = {
                "target_cities": target_cities,
                "target_roles": target_roles,
                "salary_min": p.get("salary_min"),
                "salary_max": p.get("salary_max"),
                "work_type": p.get("work_type"),
                "priorities": priorities,
                "deal_breakers": deal_breakers,
            }

    return {
        "name": row.get("name"),
        "city": row.get("city"),
        "experience": experience_str,
        "education": row.get("education_level"),
        "school": row.get("school"),
        "major": row.get("education_major"),
        "current_company": row.get("current_company"),
        "current_role": row.get("current_role"),
        "summary": row.get("summary"),
        "self_evaluation": row.get("self_evaluation"),
        "tech_stack": tech_stack,
        "tech_stack_grouped": tech_stack_grouped,
        "work_experience": work_experience,
        "projects": projects,
        "highlights": highlights,
        "job_preferences": job_preferences,
    }


def _format_salary(salary_min: int | None, salary_max: int | None) -> str:
    if salary_min and salary_max:
        return f"{salary_min}-{salary_max}K"
    if salary_min:
        return f"{salary_min}K+"
    if salary_max:
        return f"{salary_max}K"
    return "面议"


async def _load_jobs(db: Database) -> list[dict]:
    """从 jobs 表加载岗位列表，格式化给模板使用。"""
    rows = await db.execute(
        "SELECT id, url, title, company, salary_min, salary_max, city, match_score "
        "FROM jobs ORDER BY id DESC"
    )
    return [
        {
            "id": r.get("id"),
            "title": r.get("title") or "未知岗位",
            "company": r.get("company") or "未知公司",
            "salary": _format_salary(r.get("salary_min"), r.get("salary_max")),
            "city": r.get("city") or "",
            "url": r.get("url") or "#",
            "match_score": r.get("match_score"),
        }
        for r in rows
    ]


# ---- 单页面入口 ----

@app.get("/")
async def index():
    """主页 — 直接跳转 Chainlit 对话页"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/chat")


# ---- iframe 内嵌页面（/page/xxx，无导航栏） ----

@app.get("/page/settings", response_class=HTMLResponse)
async def page_settings(request: Request):
    db = await _get_db()
    settings = await _load_llm_settings(db)
    config = load_config()
    # 加载人格配置
    persona_rows = await db.execute("SELECT value FROM user_preferences WHERE key = ?", ("persona",))
    persona = persona_rows[0]["value"] if persona_rows and persona_rows[0]["value"] in ("ni", "wo") else "ni"
    return templates.TemplateResponse(request, "settings_embed.html", {
        "provider": settings.get("llm_provider") or "dashscope",
        "api_key": settings.get("llm_api_key") or config.dashscope_api_key,
        "base_url": settings.get("llm_base_url") or config.api_base_url,
        "model": settings.get("llm_model") or config.dashscope_llm_model,
        "persona": persona,
    })


@app.get("/page/jobs", response_class=HTMLResponse)
async def page_jobs(request: Request):
    db = await _get_db()
    jobs = await _load_jobs(db)
    return templates.TemplateResponse(request, "embed_wrap.html", {
        "title": "岗位数据", "content_template": "jobs_content.html", "jobs": jobs,
    })


@app.get("/page/resume", response_class=HTMLResponse)
async def page_resume(request: Request):
    db = await _get_db()
    resume = await _load_active_resume(db)
    return templates.TemplateResponse(request, "embed_wrap.html", {
        "title": "简历管理", "content_template": "resume_content.html",
        "resume": resume, "suggestions": [],
    })


def _render_md(text: str) -> str:
    """将 Markdown 文本渲染为 HTML（链接可点击、在新标签页打开）。"""
    import re as _re
    try:
        import markdown
        # 裸 URL 转 markdown 链接
        text = _re.sub(r'(?<!\[)(?<!\()(https?://\S+)', r'[\1](\1)', text)
        # 确保列表项前有空行（markdown 库严格模式需要）
        text = _re.sub(r'([^\n])\n([-*] )', r'\1\n\n\2', text)
        text = _re.sub(r'([^\n])\n(\d+\. )', r'\1\n\n\2', text)
        html = markdown.markdown(text, extensions=["tables", "fenced_code", "nl2br"])
        html = html.replace("<a ", '<a target="_blank" rel="noopener" ')
        return html
    except ImportError:
        return _re.sub(r'(https?://\S+)', r'<a href="\1" target="_blank" rel="noopener">\1</a>', text.replace("\n", "<br>"))


def _demote_headings(text: str) -> str:
    """将记忆条目 body 中的 Markdown 标题降级，避免与分类/条目标题层级冲突。

    # → ###, ## → ####, ### → #####
    同时清理 body 中残留的一级标题重复行（如 body 以 "# 标题" 开头）。
    """
    import re as _re
    # 去掉 body 开头的一级标题行（跟条目 title 重复）
    text = _re.sub(r'^#\s+.*\n*', '', text.strip())
    def _replace(m: _re.Match) -> str:
        hashes = m.group(1)
        rest = m.group(2)
        new_level = min(len(hashes) + 2, 6)
        return "#" * new_level + rest
    return _re.sub(r'^(#{1,4})([ \t]+.*)$', _replace, text, flags=_re.MULTILINE)


def _parse_memory_files(memory_dir: Path) -> list[dict]:
    """读取记忆画像文件夹下所有 .md 文件，解析为模板数据。"""
    categories = []
    if not memory_dir.is_dir():
        return categories

    for md_file in sorted(memory_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        if not content.strip():
            continue

        # 提取 # 一级标题作为分类名
        display_name = md_file.stem
        for line in content.split("\n"):
            if line.startswith("# ") and not line.startswith("## "):
                display_name = line[2:].strip()
                break

        # 按 ## 分割条目
        entries = []
        sections = re.split(r"(?m)^## ", content)
        for section in sections[1:]:  # 跳过第一段（# 标题之前的内容）
            lines = section.split("\n", 1)
            title = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""

            # 提取溯源元数据行: > 来源: xxx | 提取于: xxx
            source_id = ""
            extracted_at = ""
            body_lines = []
            for bline in body.split("\n"):
                m = re.match(r"^>\s*来源:\s*(\S+)", bline)
                if m:
                    source_id = m.group(1)
                    m2 = re.search(r"提取于:\s*(.+)", bline)
                    if m2:
                        extracted_at = m2.group(1).strip()
                    continue
                m_update = re.match(r"^>\s*(?:更新于|聚合整理于):\s*(.+)", bline)
                if m_update:
                    extracted_at = m_update.group(1).strip()
                    continue
                body_lines.append(bline)

            entries.append({
                "title": title,
                "body_html": _render_md(_demote_headings("\n".join(body_lines).strip())),
                "source_id": source_id,
                "extracted_at": extracted_at,
            })

        categories.append({"display_name": display_name, "entries": entries})

    return categories


@app.get("/page/memory", response_class=HTMLResponse)
async def page_memory(request: Request):
    db = await _get_db()
    resume = await _load_active_resume(db)
    memory_dir = _project_root / "data" / "记忆画像"
    categories = _parse_memory_files(memory_dir)
    return templates.TemplateResponse(request, "embed_wrap.html", {
        "title": "用户画像", "content_template": "memory_content.html",
        "resume": resume, "categories": categories,
    })


# ---- Settings API ----

@app.post("/api/settings")
async def save_settings(request: Request):
    try:
        body = await request.json()
        provider = body.get("provider", "dashscope")
        api_key = (body.get("api_key") or "").strip()
        base_url = (body.get("base_url") or "").strip()
        model = (body.get("model") or "").strip()

        preset = PROVIDER_PRESETS.get(provider, {})
        if not base_url:
            base_url = preset.get("base_url", "")
        if not model:
            model = preset.get("model", "")

        if not api_key:
            return JSONResponse({"ok": False, "error": "API Key 不能为空"})

        db = await _get_db()
        await _save_llm_settings(db, provider, api_key, base_url, model)

        # 同时保存人格配置（如果有）
        persona = body.get("persona", "").strip()
        if persona in ("ni", "wo"):
            await db.execute_write(
                "INSERT INTO user_preferences (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                ("persona", persona),
            )

        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/settings/test")
async def test_connection(request: Request):
    try:
        body = await request.json()
        api_key = (body.get("api_key") or "").strip()
        base_url = (body.get("base_url") or "").strip()
        model = (body.get("model") or "").strip()

        if not api_key or not base_url or not model:
            return JSONResponse({"ok": False, "error": "请填写完整的配置"})

        from agent.llm_client import LLMClient
        client = LLMClient(api_key=api_key, model=model, base_url=base_url)
        # 只验证连通性：发最短的请求，限制 max_tokens
        from openai import AsyncOpenAI
        test_client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=10)
        resp = await test_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        return JSONResponse({"ok": True, "response": "连接成功"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ---- 健康检查 ----

@app.get("/api/health")
async def api_health():
    return {"status": "ok"}


# ---- 通用 AI 调用（用用户配置的 LLM） ----

@app.post("/api/chat")
async def api_chat(request: Request):
    """通用 LLM 调用 — 使用用户配置的 API Key / Base URL / Model。"""
    try:
        body = await request.json()
        message = (body.get("message") or "").strip()
        if not message:
            return JSONResponse({"ok": False, "error": "message 不能为空"})

        db = await _get_db()
        settings = await _load_llm_settings(db)
        api_key = settings.get("llm_api_key", "")
        base_url = settings.get("llm_base_url", "")
        model = settings.get("llm_model", "")
        if not api_key or not base_url or not model:
            return JSONResponse({"ok": False, "error": "请先在设置中配置 LLM"})

        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": message}],
        )
        reply = resp.choices[0].message.content or ""
        return JSONResponse({"ok": True, "reply": reply})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ---- 测试 API ----

@app.post("/api/test/chat")
async def api_test_chat(request: Request):
    """
    通用 Agent 对话测试接口。

    使用用户配置的 LLM（OpenAI 兼容格式），自行管理 function calling 循环。
    通过 config.enable_test_api 控制开关。
    """
    import json as _json
    import time

    config = load_config()
    if not config.enable_test_api:
        return JSONResponse({"ok": False, "error": "测试 API 未启用"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "请求格式错误"}, status_code=400)

    message = body.get("message", "").strip()
    if not message:
        return JSONResponse({"ok": False, "error": "message 不能为空"}, status_code=400)

    conversation_id = body.get("conversation_id")
    history = body.get("history") or []

    db = await _get_db()
    llm_settings = await _load_llm_settings(db)
    api_key = llm_settings.get("llm_api_key", "")
    base_url = llm_settings.get("llm_base_url", "")
    model = body.get("model") or llm_settings.get("llm_model", "")

    if not api_key or not base_url or not model:
        return JSONResponse({"ok": False, "error": "未配置 LLM，请先在设置中配置"}, status_code=400)

    from openai import AsyncOpenAI

    from agent.bootstrap import create_tool_registry
    from agent.system_prompt import build_full_system_prompt

    registry, _skill_loader = create_tool_registry()
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120)

    # 工具集路由：初始只激活 core
    active_toolsets: set[str] = {"core"}

    # 构建消息
    messages = [{"role": "system", "content": build_full_system_prompt()}]
    for h in history:
        if isinstance(h, dict) and "role" in h and "content" in h:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    tool_calls_report: list[dict] = []
    reply = ""
    start_time = time.time()
    max_turns = 10

    from tools.data.conversation_logger import ConversationLogger
    conv_log_id = conversation_id or f"test-{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"
    conv_logger = ConversationLogger(conv_log_id)
    conv_logger.begin_turn(message)

    try:
        for turn in range(max_turns):
            # 每轮重新获取 schema，确保 activate_toolset 效果立即生效
            tools_schema = registry.get_schemas_for_toolsets(active_toolsets)

            conv_logger.log_llm_request(model=model, message_count=len(messages), has_tools=True)
            llm_start = time.time()

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools_schema if tools_schema else None,
            )

            choice = response.choices[0]
            llm_ms = int((time.time() - llm_start) * 1000)

            text_content = choice.message.content or ""
            tool_calls = choice.message.tool_calls or []

            if text_content:
                reply = text_content

            conv_logger.log_llm_response(
                has_text=bool(text_content),
                tool_call_count=len(tool_calls),
                duration_ms=llm_ms,
            )

            if not tool_calls:
                break

            # 把 assistant 消息加入历史（to_dict 保留 Gemini thought_signature）
            messages.append(choice.message.to_dict())

            # 执行每个 tool call
            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = _json.loads(tc.function.arguments)
                except _json.JSONDecodeError:
                    tool_args = {}

                tool_start = time.time()
                conv_logger.log_tool_start(tool_name, tool_args)
                print(f"[TEST_CHAT] Tool call: {tool_name}({_json.dumps(tool_args, ensure_ascii=False)[:100]})", flush=True)

                tool = registry.get_tool(tool_name)
                tc_report = {"name": tool_name, "display_name": registry.get_display_name(tool_name), "params": tool_args, "result": None, "success": False, "duration_ms": 0}

                if tool:
                    try:
                        from services.task_monitor import TaskMonitor

                        result = await tool.execute(tool_args, context={
                            "db": db, "task_monitor": TaskMonitor(),
                            "agent_busy_check": lambda: False,
                            "active_toolsets": active_toolsets, "registry": registry,
                        })
                        result_str = _json.dumps(result, ensure_ascii=False, default=str)[:2000] if result else "{}"
                        tc_report["success"] = True
                        tc_report["result"] = result_str
                    except Exception as e:
                        result_str = _json.dumps({"error": str(e)}, ensure_ascii=False)
                        tc_report["result"] = str(e)
                else:
                    result_str = _json.dumps({"error": f"Tool '{tool_name}' not found"})
                    tc_report["result"] = f"Tool '{tool_name}' not found"

                tc_report["duration_ms"] = int((time.time() - tool_start) * 1000)
                tool_calls_report.append(tc_report)
                conv_logger.log_tool_result(tool_name, success=tc_report["success"], duration_ms=tc_report["duration_ms"], result_preview=tc_report["result"] or "")
                print(f"[TEST_CHAT]   -> {'✅' if tc_report['success'] else '❌'} {tc_report['duration_ms']}ms", flush=True)

                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

    except Exception as e:
        import traceback
        print(f"[TEST_CHAT] EXCEPTION: {e}", flush=True)
        traceback.print_exc()
        conv_logger.log_llm_error(str(e))
        conv_logger.end_turn(f"ERROR: {e}")
        return JSONResponse({"ok": False, "error": f"Agent 执行失败: {e}"}, status_code=500)

    total_duration_ms = int((time.time() - start_time) * 1000)
    conv_logger.end_turn(reply or "(no reply)")
    print(f"[TEST_CHAT] Done. reply={reply[:80] if reply else '(empty)'}, tools={len(tool_calls_report)}, {total_duration_ms}ms", flush=True)

    return JSONResponse({
        "ok": True, "reply": reply, "tool_calls": tool_calls_report,
        "conversation_id": conversation_id or "", "total_duration_ms": total_duration_ms,
        "model": model, "token_usage": {"prompt": 0, "completion": 0},
    })


# ---- 任务状态 API（供前端任务面板轮询） ----

@app.get("/api/tasks")
async def api_get_tasks():
    """返回当前活跃的任务列表（运行中 + 最近完成的）"""
    from services.task_state import TaskStateStore
    db = await _get_db()
    store = TaskStateStore(db)
    tasks = await store.get_active()
    return JSONResponse({"tasks": tasks})


@app.post("/api/tasks/{platform}/stop")
async def api_stop_task(platform: str):
    """停止指定平台的采集任务（Playwright 模式下暂不支持）"""
    return JSONResponse({"success": False, "error": "暂不支持停止任务"})


@app.get("/api/jobs")
async def api_list_jobs(
    page: int = 1,
    size: int = 20,
    city: str = "",
    keyword: str = "",
    salary_min: int = 0,
    salary_max: int = 0,
    has_jd: bool = False,
    sort: str = "",
    order: str = "desc",
):
    """岗位列表 API，支持分页、筛选和排序"""
    db = await _get_db()
    conditions = []
    params: list = []

    if has_jd:
        conditions.append("raw_jd IS NOT NULL AND raw_jd != ''")
    if city:
        conditions.append("city LIKE ?")
        params.append(f"%{city}%")
    if keyword:
        conditions.append("(title LIKE ? OR company LIKE ?)")
        params.append(f"%{keyword}%")
        params.append(f"%{keyword}%")
    if salary_min > 0:
        conditions.append("salary_min >= ?")
        params.append(salary_min)
    if salary_max > 0:
        conditions.append("salary_max <= ?")
        params.append(salary_max)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    # 排序（白名单防注入）
    _allowed = {"salary_min": "salary_min", "match_score": "match_score"}
    direction = "ASC" if order == "asc" else "DESC"
    order_clause = f"{_allowed[sort]} {direction} NULLS LAST, id DESC" if sort in _allowed else "id DESC"

    # 总数
    count_rows = await db.execute(f"SELECT COUNT(*) as cnt FROM jobs{where}", tuple(params))
    total = count_rows[0]["cnt"] if count_rows else 0

    # 分页数据
    offset = (page - 1) * size
    rows = await db.execute(
        f"SELECT id, url, title, company, salary_min, salary_max, city, match_score FROM jobs{where} ORDER BY {order_clause} LIMIT ? OFFSET ?",
        tuple(params) + (size, offset),
    )

    jobs = [
        {
            "id": r.get("id"),
            "title": r.get("title") or "未知岗位",
            "company": r.get("company") or "未知公司",
            "salary": _format_salary(r.get("salary_min"), r.get("salary_max")),
            "city": r.get("city") or "",
            "url": r.get("url") or "#",
            "match_score": r.get("match_score"),
        }
        for r in rows
    ]
    city_rows = await db.execute(
        "SELECT DISTINCT CASE WHEN city LIKE '%-%' THEN SUBSTR(city, 1, INSTR(city, '-') - 1) ELSE city END as main_city "
        "FROM jobs WHERE city != '' ORDER BY main_city"
    )
    cities = [r["main_city"] for r in city_rows if r["main_city"]]

    return JSONResponse({
        "jobs": jobs,
        "total": total,
        "page": page,
        "size": size,
        "total_pages": (total + size - 1) // size if size > 0 else 0,
        "cities": cities,
    })




# ---- 简历 API ----

@app.get("/api/resume")
async def api_resume():
    """获取当前活跃简历 + 求职意向"""
    db = await _get_db()
    rows = await db.execute("SELECT * FROM resumes WHERE is_active = 1 LIMIT 1")
    if not rows:
        return JSONResponse({"resume": None})
    import json as _json
    r = rows[0]
    pref_rows = await db.execute("SELECT * FROM job_preferences WHERE is_active = 1 LIMIT 1")
    p = pref_rows[0] if pref_rows else {}
    def _j(v):
        try: return _json.loads(v) if v else []
        except: return []
    return JSONResponse({"resume": {
        "name": r.get("name") or "", "education_level": r.get("education_level") or "",
        "education_major": r.get("education_major") or "", "school": r.get("school") or "",
        "years_of_experience": r.get("years_of_experience"), "current_role": r.get("current_role") or "",
        "current_company": r.get("current_company") or "", "summary": r.get("summary") or "",
        "skills_flat": _j(r.get("skills_flat")), "projects": _j(r.get("projects")),
        "highlights": _j(r.get("highlights")), "work_experience": _j(r.get("work_experience")),
        "target_roles": _j(p.get("target_roles")), "salary_min": p.get("salary_min"),
        "salary_max": p.get("salary_max"), "target_cities": _j(p.get("target_cities")),
    }})


@app.put("/api/resume")
async def api_update_resume(request: Request):
    """更新简历数据（前端编辑保存）"""
    from web.resume_service import ResumeService

    db = await _get_db()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "请求格式错误"}, status_code=400)

    svc = ResumeService(db)
    result = await svc.update_resume(body)
    return JSONResponse({"ok": True, "fields": result["fields"]})


@app.get("/api/resume/export/docx")
async def api_resume_export_docx():
    """导出当前活跃简历为 DOCX 文件下载。"""
    from web.resume_service import ResumeService

    db = await _get_db()
    svc = ResumeService(db)
    try:
        docx_bytes, filename = await svc.export_docx()
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=404)

    from starlette.responses import Response
    encoded = urllib.parse.quote(filename)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename*=UTF-8\'\'{encoded}'},
    )


@app.post("/api/resume/upload")
async def api_resume_upload(request: Request):
    """上传简历文件（PDF/DOCX），解析文本后自动填充字段。

    不需要 LLM：使用正则 + 关键词提取结构化字段。
    """
    import json as _json
    import tempfile

    form = await request.form()
    file = form.get("file")
    if file is None:
        return JSONResponse({"ok": False, "error": "未选择文件"}, status_code=400)

    filename = getattr(file, "filename", "") or ""
    ext = Path(filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".doc", ".md", ".txt"):
        return JSONResponse({"ok": False, "error": "仅支持 PDF / DOCX / MD / TXT 格式"}, status_code=400)

    # 保存临时文件并解析
    content_bytes = await file.read()
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content_bytes)
        tmp_path = tmp.name

    try:
        raw_text = _parse_resume_file(tmp_path, ext)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not raw_text:
        return JSONResponse({"ok": False, "error": "文件解析失败，内容为空"}, status_code=400)

    # 结构化提取（纯规则，不需要 LLM）
    extracted = _extract_resume_fields(raw_text)

    # 写入数据库
    from web.resume_service import ResumeService

    db = await _get_db()
    svc = ResumeService(db)
    # 同时保存 raw_text
    extracted["raw_text"] = raw_text
    result = await svc.update_resume(extracted)

    return JSONResponse({"ok": True, "fields": result["fields"], "extracted": extracted})


def _parse_resume_file(file_path: str, ext: str) -> str | None:
    """解析简历文件为纯文本。"""
    try:
        if ext in (".md", ".txt"):
            return Path(file_path).read_text(encoding="utf-8")
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
    except Exception:
        return None
    return None


def _extract_resume_fields(text: str) -> dict:
    """从简历纯文本中用规则提取结构化字段（不依赖 LLM）。"""
    data: dict = {}

    lines = text.strip().splitlines()
    # 姓名：通常是第一行非空短文本
    for line in lines:
        line = line.strip()
        if line and len(line) <= 10 and not re.search(r"[：:@\d{4}]", line):
            data["name"] = line
            break

    # 手机
    m = re.search(r"1[3-9]\d{9}", text)
    if m:
        data["phone"] = m.group()

    # 邮箱
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    if m:
        data["email"] = m.group()

    # 城市 — 常见关键词后
    m = re.search(r"(?:现居|城市|所在地|居住地)[：:\s]*(\S{2,6})", text)
    if m:
        data["city"] = m.group(1)

    # 学历
    for kw in ("博士", "硕士", "本科", "大专"):
        if kw in text:
            data["education_level"] = kw
            break

    # 学校
    m = re.search(r"(?:学校|毕业院校|院校)[：:\s]*(.+?)(?:\s|$)", text)
    if m:
        data["school"] = m.group(1).strip()

    # 专业
    m = re.search(r"(?:专业)[：:\s]*(.+?)(?:\s|$)", text)
    if m:
        data["education_major"] = m.group(1).strip()

    # 工作年限
    m = re.search(r"(\d{1,2})\s*年(?:工作|以上)?(?:经验|经历)?", text)
    if m:
        data["years_of_experience"] = int(m.group(1))

    # 当前公司 / 职位 — 从工作经历第一段提取
    m = re.search(r"(?:当前公司|现任公司|公司)[：:\s]*(.+?)(?:\s|$)", text)
    if m:
        data["current_company"] = m.group(1).strip()

    m = re.search(r"(?:当前职位|现任职位|职位|岗位)[：:\s]*(.+?)(?:\s|$)", text)
    if m:
        data["current_role"] = m.group(1).strip()

    # 个人简介 / 自我评价
    for label, field in [("个人简介", "summary"), ("自我评价", "self_evaluation"),
                         ("个人总结", "summary"), ("自我描述", "self_evaluation")]:
        m = re.search(rf"{label}[：:\s]*\n?([\s\S]*?)(?=\n{{2,}}|\Z)", text)
        if m and m.group(1).strip():
            data[field] = m.group(1).strip()[:500]

    # 技术栈 — 提取常见技术关键词
    tech_keywords = {
        "Python", "Java", "JavaScript", "TypeScript", "Go", "Rust", "C++", "C#",
        "React", "Vue", "Angular", "Node.js", "FastAPI", "Django", "Flask", "Spring",
        "Docker", "Kubernetes", "K8s", "AWS", "GCP", "Azure",
        "MySQL", "PostgreSQL", "Redis", "MongoDB", "Elasticsearch",
        "PyTorch", "TensorFlow", "LLM", "RAG", "Agent", "NLP", "BERT", "GPT",
        "Git", "Linux", "Nginx", "Kafka", "RabbitMQ", "GraphQL", "REST",
    }
    found_tech = [kw for kw in tech_keywords if re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE)]
    if found_tech:
        data["tech_stack"] = sorted(found_tech)

    return data


# ---- 岗位详情 ----

@app.get("/api/jobs/{job_id}")
async def api_job_detail(job_id: int):
    db = await _get_db()
    rows = await db.execute(
        "SELECT id, url, platform, title, company, salary_min, salary_max, salary_months, "
        "city, experience, education, company_size, company_industry, "
        "recruiter_name, recruiter_title, raw_jd, match_score, match_detail, discovered_at "
        "FROM jobs WHERE id = ?", (job_id,)
    )
    if not rows:
        return JSONResponse({"error": "岗位不存在"}, status_code=404)
    r = rows[0]
    return JSONResponse({
        "id": r["id"], "url": r.get("url") or "", "platform": r.get("platform") or "",
        "title": r.get("title") or "", "company": r.get("company") or "",
        "salary": _format_salary(r.get("salary_min"), r.get("salary_max")),
        "salary_months": r.get("salary_months"),
        "city": r.get("city") or "", "experience": r.get("experience") or "",
        "education": r.get("education") or "",
        "company_size": r.get("company_size") or "",
        "company_industry": r.get("company_industry") or "",
        "recruiter_name": r.get("recruiter_name") or "",
        "recruiter_title": r.get("recruiter_title") or "",
        "raw_jd": r.get("raw_jd") or "",
        "match_score": r.get("match_score"),
        "match_detail": r.get("match_detail") or "",
        "discovered_at": r.get("discovered_at") or "",
    })

@app.post("/api/jobs/{job_id}/analysis")
async def api_save_job_analysis(job_id: int, request: Request):
    """AI 深度分析：后端分步处理，精准匹配。"""
    import json as _json

    db = await _get_db()

    # 1. 读岗位数据
    rows = await db.execute(
        "SELECT id, title, company, salary_min, salary_max, salary_months, city, "
        "experience, education, company_size, company_industry, raw_jd "
        "FROM jobs WHERE id = ?", (job_id,)
    )
    if not rows:
        return JSONResponse({"ok": False, "error": "岗位不存在"}, status_code=404)
    job = rows[0]

    raw_jd = job.get("raw_jd") or ""
    if not raw_jd:
        return JSONResponse({"ok": False, "error": "该岗位暂无 JD 数据，请先获取详情"})

    # 2. 读用户简历（只取分析需要的字段）
    resume_data = await _load_active_resume(db)

    resume_section = ""
    if resume_data.get("name"):
        skills = ", ".join(resume_data.get("tech_stack") or [])
        work_exp = []
        for w in (resume_data.get("work_experience") or [])[:3]:
            ts = w.get("tech_stack", "")
            if isinstance(ts, list):
                ts = ", ".join(ts)
            work_exp.append(f"{w.get('role','')}@{w.get('company','')}({w.get('duration','')}): {ts}")
        projects = []
        for p in (resume_data.get("projects") or [])[:3]:
            ts = p.get("tech_stack", "")
            if isinstance(ts, list):
                ts = ", ".join(ts)
            projects.append(f"{p.get('name','')}: {ts}")

        jp = resume_data.get("job_preferences") or {}
        resume_section = f"""
候选人信息：
- 学历：{resume_data.get('education','未知')}，{resume_data.get('major','')}，{resume_data.get('school','')}
- 工作年限：{resume_data.get('experience','未知')}
- 当前职位：{resume_data.get('current_role','')}（{resume_data.get('current_company','')}）
- 核心技能：{skills}
- 工作经历：{'; '.join(work_exp)}
- 项目经验：{'; '.join(projects)}
- 期望薪资：{jp.get('salary_min','?')}-{jp.get('salary_max','?')}K
- 期望城市：{jp.get('target_cities','未知')}"""

    # 3. 读记忆画像（职业规划、求职目标、要点信息等软性维度）
    memory_section = ""
    from pathlib import Path as _MemPath
    memory_dir = _MemPath(__file__).parent.parent / "data" / "记忆画像"
    relevant_files = ["职业规划.md", "求职冲刺目标.md", "要点信息.md", "个人需求.md", "价值观.md"]
    memory_parts = []
    for fname in relevant_files:
        fpath = memory_dir / fname
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8").strip()
            if content and len(content) > 20:
                # 截取前 500 字，避免 prompt 过长
                memory_parts.append(f"【{fname.replace('.md','')}】\n{content[:500]}")
    if memory_parts:
        memory_section = "\n\n候选人画像（来自对话记忆，反映真实偏好和软性特征）：\n" + "\n\n".join(memory_parts)

    # 3. 构建精准 prompt
    salary = _format_salary(job.get("salary_min"), job.get("salary_max"))
    prompt = f"""你是一位专业的求职顾问。请对以下岗位与候选人进行匹配分析。

分析需要结合两个维度：
1. 简历 vs JD：硬性条件对比（技能、学历、经验、薪资）
2. 画像 vs JD：软性匹配（职业方向契合度、文化偏好、成长空间）

严格按以下 JSON 格式返回，不要输出任何其他内容：
{{"overall_score":0-100,"verdict":"一句话结论","summary":"2-3句总体分析","hard_check":[{{"dimension":"学历","requirement":"","candidate":"","status":"pass/fail/warn/na","note":""}},{{"dimension":"经验年限","requirement":"","candidate":"","status":"","note":""}},{{"dimension":"薪资匹配","requirement":"","candidate":"","status":"","note":""}},{{"dimension":"城市","requirement":"","candidate":"","status":"","note":""}}],"dimensions":[{{"name":"技术匹配","score":0-100,"detail":""}},{{"name":"经验匹配","score":0-100,"detail":""}},{{"name":"项目相关性","score":0-100,"detail":""}},{{"name":"职业方向契合","score":0-100,"detail":"基于候选人画像中的职业规划和求职目标"}},{{"name":"文化与偏好契合","score":0-100,"detail":"基于候选人画像中的价值观和个人需求"}}],"skills":{{"matched":[],"missing":[],"bonus":[]}},"strengths":[],"gaps":[],"suggestions":[],"interview_tips":[],"profile_insights":"基于候选人画像的额外洞察（如：该岗位是否符合候选人的长期规划、是否匹配其偏好的工作模式等），2-3句话"}}

岗位信息：
- 职位：{job.get('title','')}
- 公司：{job.get('company','')}（{job.get('company_industry','未知')}，{job.get('company_size','未知')}）
- 薪资：{salary}{('·'+str(job.get('salary_months'))+'薪') if job.get('salary_months') else ''}
- 城市：{job.get('city','')}
- 经验要求：{job.get('experience','未知')}
- 学历要求：{job.get('education','未知')}
- JD：{raw_jd[:1500]}
{resume_section}
{memory_section}"""

    # 4. 调 LLM
    settings = await _load_llm_settings(db)
    api_key = settings.get("llm_api_key", "")
    base_url = settings.get("llm_base_url", "")
    model = settings.get("llm_model", "")
    if not api_key or not base_url or not model:
        return JSONResponse({"ok": False, "error": "请先在设置中配置 LLM"})

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=None)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        reply = resp.choices[0].message.content or ""
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"LLM 调用失败: {e}"})

    # 5. 解析 JSON
    analysis = None
    try:
        import re
        m = re.search(r'\{[\s\S]*\}', reply)
        if m:
            analysis = _json.loads(m.group(0))
    except Exception:
        pass

    if not analysis:
        return JSONResponse({"ok": False, "error": "LLM 返回格式异常", "raw_reply": reply[:500]})

    # 6. 持久化
    score = analysis.get("overall_score", 0)
    await db.execute_write(
        "UPDATE jobs SET match_score = ?, match_detail = ?, parsed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (score, _json.dumps(analysis, ensure_ascii=False), job_id),
    )

    return JSONResponse({"ok": True, "analysis": analysis})


@app.post("/api/jobs/{job_id}/fetch-detail")
async def api_fetch_job_detail(job_id: int, request: Request):
    """获取单个岗位 JD — 使用 Playwright 直接抓取猎聘详情页"""
    db = await _get_db()

    rows = await db.execute(
        "SELECT id, url, title, raw_jd FROM jobs WHERE id = ?", (job_id,)
    )
    if not rows:
        return JSONResponse({"success": False, "error": "岗位不存在"}, status_code=404)

    row = rows[0]
    url = row.get("url") or ""
    if not url or url == "#":
        return JSONResponse({"success": False, "error": "该岗位没有详情链接"})

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    force = body.get("force", False)

    # 已有 JD 且不强制 → 跳过
    if row.get("raw_jd") and not force:
        return JSONResponse({"success": True, "fetched": 0, "skipped": 1, "results": [
            {"id": job_id, "title": row.get("title", ""), "source": "cache"}
        ]})

    # 使用 Playwright 获取
    from browser.liepin import LiepinBrowser

    browser = LiepinBrowser(headless=True)
    try:
        await browser.init()
        jd_text = await browser.fetch_job_detail(url)
    finally:
        await browser.close()

    if jd_text:
        await db.execute_write(
            "UPDATE jobs SET raw_jd = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (jd_text, job_id),
        )
        return JSONResponse({"success": True, "fetched": 1, "skipped": 0, "results": [
            {"id": job_id, "title": row.get("title", ""), "jd_preview": jd_text[:200]}
        ]})
    else:
        return JSONResponse({"success": False, "fetched": 0, "failed": 1, "error": "未能提取 JD 内容",
                             "results": [{"id": job_id, "error": "JD 提取失败"}]})


@app.post("/api/jobs/{job_id}/greeting")
async def api_generate_greeting(job_id: int, request: Request):
    """基于分析结果 + 用户画像，AI 生成个性化打招呼语"""
    import json as _json

    db = await _get_db()
    rows = await db.execute(
        "SELECT id, title, company, raw_jd, match_detail FROM jobs WHERE id = ?", (job_id,)
    )
    if not rows:
        return JSONResponse({"ok": False, "error": "岗位不存在"}, status_code=404)
    job = rows[0]

    if not job.get("raw_jd"):
        return JSONResponse({"ok": False, "error": "该岗位暂无 JD，请先获取详情"})
    if not job.get("match_detail"):
        return JSONResponse({"ok": False, "error": "请先完成 AI 分析"})

    # 解析分析结果
    try:
        analysis = _json.loads(job["match_detail"])
    except Exception:
        analysis = {}

    # 读用户简历
    resume_data = await _load_active_resume(db)
    resume_section = ""
    if resume_data.get("name"):
        skills = ", ".join(resume_data.get("tech_stack") or [])
        resume_section = f"候选人：{resume_data.get('name','')}，{resume_data.get('current_role','')}，核心技能：{skills}"

    # 读记忆画像（语言风格、沟通偏好）
    memory_section = ""
    from pathlib import Path as _MemPath
    memory_dir = _MemPath(__file__).parent.parent / "data" / "记忆画像"
    for fname in ["语言风格.md", "沟通偏好.md", "求职冲刺目标.md"]:
        fpath = memory_dir / fname
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8").strip()
            if content and len(content) > 10:
                memory_section += f"\n【{fname.replace('.md','')}】{content[:300]}"

    strengths = ", ".join(analysis.get("strengths", [])[:3])
    matched_skills = ", ".join((analysis.get("skills") or {}).get("matched", [])[:5])

    prompt = f"""你是一位求职打招呼语生成专家。请根据以下信息，生成一段个性化的打招呼语。

要求：
1. 控制在 150 字以内
2. 自然真诚，不要模板化
3. 突出与岗位匹配的核心优势
4. 体现候选人的个人特色和语言风格
5. 直接输出打招呼语文本，不要加任何前缀或解释

岗位：{job.get('title','')} @ {job.get('company','')}
JD 摘要：{(job.get('raw_jd') or '')[:500]}

匹配分析：
- 总分：{analysis.get('overall_score', '?')}
- 核心优势：{strengths}
- 匹配技能：{matched_skills}
- 结论：{analysis.get('verdict', '')}

{resume_section}
{memory_section}"""

    settings = await _load_llm_settings(db)
    api_key = settings.get("llm_api_key", "")
    base_url = settings.get("llm_base_url", "")
    model = settings.get("llm_model", "")
    if not api_key or not base_url or not model:
        return JSONResponse({"ok": False, "error": "请先在设置中配置 LLM"})

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        greeting = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"LLM 调用失败: {e}"})

    if not greeting:
        return JSONResponse({"ok": False, "error": "生成结果为空"})

    return JSONResponse({"ok": True, "greeting": greeting})


@app.post("/api/jobs/{job_id}/send-greeting")
async def api_send_greeting(job_id: int, request: Request):
    """生成打招呼语并通过 Playwright 自动在猎聘发送"""
    import json as _json

    db = await _get_db()
    rows = await db.execute(
        "SELECT id, title, company, url, raw_jd, match_detail FROM jobs WHERE id = ?", (job_id,)
    )
    if not rows:
        return JSONResponse({"ok": False, "error": "岗位不存在"}, status_code=404)
    job = rows[0]

    url = job.get("url") or ""
    if not url or url == "#":
        return JSONResponse({"ok": False, "error": "该岗位没有详情链接"})

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    # 如果前端传了自定义打招呼语就用，否则 AI 生成
    greeting = (body.get("greeting") or "").strip()

    if not greeting:
        if not job.get("raw_jd"):
            return JSONResponse({"ok": False, "error": "该岗位暂无 JD，请先获取详情"})

        # 解析分析结果
        analysis = {}
        if job.get("match_detail"):
            try:
                analysis = _json.loads(job["match_detail"])
            except Exception:
                pass

        resume_data = await _load_active_resume(db)
        resume_section = ""
        if resume_data.get("name"):
            skills = ", ".join(resume_data.get("tech_stack") or [])
            resume_section = f"候选人：{resume_data.get('name','')}，{resume_data.get('current_role','')}，核心技能：{skills}"

        strengths = ", ".join(analysis.get("strengths", [])[:3])
        matched_skills = ", ".join((analysis.get("skills") or {}).get("matched", [])[:5])

        prompt = f"""生成一段简洁、自然的打招呼语（不超过80字）。
要求：体现求职者与岗位的匹配点，语气真诚专业，不要模板化。直接输出打招呼语。

岗位：{job.get('title','')} @ {job.get('company','')}
JD 摘要：{(job.get('raw_jd') or '')[:500]}
匹配优势：{strengths}
匹配技能：{matched_skills}
{resume_section}"""

        settings = await _load_llm_settings(db)
        api_key = settings.get("llm_api_key", "")
        base_url = settings.get("llm_base_url", "")
        model = settings.get("llm_model", "")
        if not api_key or not base_url or not model:
            return JSONResponse({"ok": False, "error": "请先在设置中配置 LLM"})

        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120)
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            greeting = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"生成打招呼语失败: {e}"})

    if not greeting:
        return JSONResponse({"ok": False, "error": "打招呼语为空"})

    # 用 Playwright 发送
    from browser.liepin import LiepinBrowser

    browser = LiepinBrowser(headless=False)
    try:
        await browser.init()
        ok = await browser.deliver(url, greeting)
    finally:
        await browser.close()

    if ok:
        # 记录投递
        await db.execute_write(
            "INSERT INTO applications (job_id, greeting, status, applied_at) "
            "VALUES (?, ?, 'sent', CURRENT_TIMESTAMP)",
            (job_id, greeting),
        )
        return JSONResponse({"ok": True, "greeting": greeting, "sent": True})
    else:
        return JSONResponse({"ok": False, "greeting": greeting, "sent": False,
                             "error": "发送失败（可能未登录或按钮未找到），打招呼语已生成可手动复制"})


@app.get("/job/{job_id}")
async def job_detail_page(job_id: int):
    from fastapi.responses import FileResponse
    return FileResponse(
        str(Path(__file__).parent / "static" / "job_detail.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ---- AI 替代性分析 ----

@app.get("/analysis/ai-exposure")
async def ai_exposure_page():
    from fastapi.responses import FileResponse
    return FileResponse(
        str(Path(__file__).parent / "static" / "ai_exposure.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/analysis/ai-exposure")
async def api_ai_exposure_get():
    """读取缓存的 AI 替代性分析结果"""
    import json as _json
    db = await _get_db()
    rows = await db.execute("SELECT value FROM user_preferences WHERE key = ?", ("ai_exposure_analysis",))
    if rows and rows[0].get("value"):
        try:
            return JSONResponse({"ok": True, "analysis": _json.loads(rows[0]["value"]), "cached": True})
        except Exception:
            pass
    return JSONResponse({"ok": True, "analysis": None, "cached": False})


@app.post("/api/analysis/ai-exposure")
async def api_ai_exposure():
    """基于用户画像 + Anthropic Economic Index 生成 AI 替代性分析。

    流程：确定性数据匹配 → 精简数据组装 → LLM 解读 → 持久化
    """
    import json as _json

    from openai import AsyncOpenAI

    from services.exposure_data import get_task_details, match_occupation

    db = await _get_db()
    resume = await _load_active_resume(db)
    if not resume.get("name") and not resume.get("tech_stack"):
        return JSONResponse({"ok": False, "error": "请先完善用户画像（简历信息）"})

    settings = await _load_llm_settings(db)
    api_key = settings.get("llm_api_key")
    if not api_key:
        return JSONResponse({"ok": False, "error": "请先在设置页面配置 API Key"})

    base_url = settings.get("llm_base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model = settings.get("llm_model") or "qwen3.5-flash"

    # ---- Step 1: 确定性匹配 ----
    query_terms = []
    if resume.get("current_role"):
        query_terms.append(resume["current_role"])
    if resume.get("job_preferences") and resume["job_preferences"].get("target_roles"):
        query_terms.extend(resume["job_preferences"]["target_roles"])

    matched_occs = []
    seen = set()
    for term in query_terms[:5]:
        for occ in match_occupation(term):
            if occ["occ_code"] not in seen:
                seen.add(occ["occ_code"])
                matched_occs.append(occ)

    if not matched_occs:
        return JSONResponse({
            "ok": True,
            "analysis": {
                "no_match": True,
                "message": "未能匹配到对应的 O*NET 职业数据。当前映射表可能不包含你的岗位，后续会持续扩充。",
                "query_terms": query_terms,
            },
        })

    # ---- Step 2: 获取任务级数据（已自动翻译为中文） ----
    occ_codes = [o["occ_code"] for o in matched_occs]
    task_data = get_task_details(occ_codes)

    # ---- Step 3: 组装精简数据给 LLM ----
    profile_parts = []
    if resume.get("current_role"):
        profile_parts.append(f"当前职位: {resume['current_role']}")
    if resume.get("tech_stack"):
        profile_parts.append(f"技术栈: {', '.join(resume['tech_stack'][:15])}")
    if resume.get("experience"):
        profile_parts.append(f"经验: {resume['experience']}")
    if resume.get("summary"):
        profile_parts.append(f"简介: {resume['summary'][:200]}")
    if resume.get("job_preferences") and resume["job_preferences"].get("target_roles"):
        profile_parts.append(f"目标岗位: {', '.join(resume['job_preferences']['target_roles'])}")
    profile_text = "\n".join(profile_parts)

    occ_text = "\n".join(
        f"- {o['title']} (替代率: {o['exposure']:.2%})" for o in matched_occs
    )

    high_tasks = "\n".join(
        f"- [{t['penetration']:.0%}] {t['task']}" for t in task_data["high_penetration"]
    )
    low_tasks = "\n".join(
        f"- [{t['penetration']:.0%}] {t['task']}" for t in task_data["low_penetration"]
    )

    prompt = f"""你是 AI 与劳动力市场分析专家。基于以下确定性数据，为用户生成中文的 AI 替代性分析报告。

## 用户画像
{profile_text}

## 匹配的 O*NET 职业及 AI 替代率（来自 Anthropic Economic Index，美国数据）
{occ_text}

## 该职业中 AI 渗透率最高的任务（最可能被 AI 增强或替代）
{high_tasks}

## 该职业中 AI 渗透率最低的任务（AI 难以替代）
{low_tasks}

## 统计摘要
- 关联任务总数: {task_data['total_tasks']}
- 任务平均渗透率: {task_data['avg_penetration']:.2%}

## 输出要求
请输出以下 JSON（不要输出其他内容，不要用 markdown 代码块包裹）：

{{"verdict": "一句话总结", "summary": "2-3 句整体分析", "dimensions": [{{"name": "增强潜力", "score": 0-100, "description": "说明"}}, {{"name": "替代风险", "score": 0-100, "description": "说明"}}, {{"name": "自动化程度", "score": 0-100, "description": "说明"}}, {{"name": "技能独特性", "score": 0-100, "description": "说明"}}], "augmentation": {{"summary": "总结", "items": ["场景1", "场景2"]}}, "automation_risk": {{"summary": "总结", "items": ["风险1", "风险2"]}}, "skill_transition": {{"summary": "总结", "items": ["建议1", "建议2"]}}, "suggestions": ["行动建议1", "行动建议2"]}}"""

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        analysis = _json.loads(raw)

        # 附加确定性数据
        analysis["matched_occupations"] = matched_occs
        analysis["task_data"] = {
            "high_penetration": task_data["high_penetration"],
            "low_penetration": task_data["low_penetration"],
            "total_tasks": task_data["total_tasks"],
            "avg_penetration": task_data["avg_penetration"],
        }
        if matched_occs:
            analysis["overall_exposure"] = round(
                sum(o["exposure"] for o in matched_occs) / len(matched_occs), 4
            )

        # ---- 持久化 ----
        await db.execute_write(
            "INSERT INTO user_preferences (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            ("ai_exposure_analysis", _json.dumps(analysis, ensure_ascii=False)),
        )

        return JSONResponse({"ok": True, "analysis": analysis})
    except _json.JSONDecodeError:
        return JSONResponse({"ok": False, "error": "AI 返回格式异常，请重试"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ---- 一键智能求职 ----

@app.get("/autopilot", response_class=HTMLResponse)
async def autopilot_page(request: Request):
    return templates.TemplateResponse(request, "autopilot.html", {
        "title": "一键智能求职", "active": "autopilot",
    })


@app.post("/api/autopilot")
async def api_autopilot():
    """一键智能求职 SSE 端点 — 流式返回每步进度和最终结果。

    全流程：画像检查 → 本地数据检查 → 程序化过滤 → JD覆盖检查 → 量化匹配 → TopN
    """
    import asyncio
    import json as _json
    import re as _re

    from fastapi.responses import StreamingResponse
    from openai import AsyncOpenAI

    db = await _get_db()

    # ---- 程序化评分函数（不消耗 token） ----
    _EDU_LEVEL = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}

    def _calc_salary(u_min, u_max, j_min, j_max):
        if not j_min and not j_max:
            return 50
        if not u_min:
            return 50
        j_min, j_max = j_min or 0, j_max or j_min or 0
        u_min, u_max = u_min or 0, u_max or u_min or 0
        overlap = min(u_max, j_max) - max(u_min, j_min)
        span = max(u_max, j_max) - min(u_min, j_min)
        return max(0, min(100, int(overlap / span * 100))) if span else 100

    def _calc_location(job_city, targets):
        if not targets:
            return 100
        return 100 if any(t in (job_city or "") for t in targets) else 0

    def _calc_edu(user_edu, job_edu):
        if not job_edu or "不限" in job_edu:
            return 100
        u, j = _EDU_LEVEL.get(user_edu, 2), _EDU_LEVEL.get(job_edu, 2)
        return 100 if u >= j else (60 if u == j - 1 else 20)

    def _calc_exp(user_years, job_exp):
        if not job_exp or "不限" in job_exp:
            return 100
        if not user_years:
            return 50
        m = _re.search(r"(\d+)\s*[-–]\s*(\d+)", job_exp)
        lo, hi = (int(m.group(1)), int(m.group(2))) if m else (int(s.group(1)), int(s.group(1)) + 5) if (s := _re.search(r"(\d+)", job_exp)) else (0, 99)
        if lo <= user_years <= hi:
            return 100
        return 70 if user_years > hi else (60 if user_years >= lo - 1 else 30)

    async def _stream():
        def _evt(step, status, detail="", results=None):
            d = {"step": step, "status": status, "detail": detail}
            if results is not None:
                d["results"] = results
            return f"data: {_json.dumps(d, ensure_ascii=False)}\n\n"

        # ---- Step 1: 检查画像 ----
        yield _evt(1, "running", "正在检查用户画像...")
        rows = await db.execute("SELECT * FROM resumes WHERE is_active = 1 LIMIT 1")
        if not rows or not rows[0].get("name"):
            yield _evt(1, "error", "未找到简历，请先上传简历")
            return
        resume = rows[0]
        pref_rows = await db.execute("SELECT * FROM job_preferences WHERE is_active = 1 LIMIT 1")
        prefs = pref_rows[0] if pref_rows else {}

        def _j(v):
            try:
                return _json.loads(v) if v else []
            except Exception:
                return []

        target_cities = _j(prefs.get("target_cities"))
        target_roles = _j(prefs.get("target_roles"))
        skills = _j(resume.get("skills_flat"))
        salary_min = prefs.get("salary_min")
        salary_max = prefs.get("salary_max")
        user_edu = resume.get("education_level", "")
        user_years = resume.get("years_of_experience")
        name = resume.get("name", "")
        city = target_cities[0] if target_cities else resume.get("city", "")
        deal_breakers = _j(prefs.get("deal_breakers"))

        summary = name
        if city:
            summary += f"，{city}"
        if target_roles:
            summary += f"，目标: {', '.join(target_roles[:3])}"
        yield _evt(1, "done", f"✅ {summary}")

        # ---- Step 2: 构建搜索条件 ----
        yield _evt(2, "running", "构建搜索条件...")
        keywords = target_roles[:3] if target_roles else skills[:3]
        if not keywords:
            keywords = [resume.get("current_role", "工程师")]
        config_desc = f"关键词: {keywords}, 城市: {city or '不限'}"
        if salary_min:
            config_desc += f", 薪资: {salary_min}-{salary_max}K"
        yield _evt(2, "done", f"✅ {config_desc}")

        # ---- Step 3: 查本地数据 ----
        yield _evt(3, "running", "检查本地岗位数据...")

        # 查本地匹配数据
        conditions, params_list = [], []
        if city:
            conditions.append("city LIKE ?")
            params_list.append(f"%{city}%")
        if keywords:
            kw_parts = []
            for kw in keywords:
                kw_parts.append("(title LIKE ? OR raw_jd LIKE ?)")
                params_list.extend([f"%{kw}%", f"%{kw}%"])
            conditions.append(f"({' OR '.join(kw_parts)})")
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        count_rows = await db.execute(f"SELECT COUNT(*) as cnt FROM jobs{where}", tuple(params_list))
        local_count = count_rows[0]["cnt"] if count_rows else 0

        if local_count == 0:
            total_rows = await db.execute("SELECT COUNT(*) as cnt FROM jobs")
            total = total_rows[0]["cnt"] if total_rows else 0
            yield _evt(3, "done", f"⚠️ 匹配 0 条（总 {total} 条），建议在对话中触发采集后再来")
            return
        yield _evt(3, "done", f"✅ 本地 {local_count} 条匹配岗位")

        # ---- Step 4: 程序化过滤 ----
        yield _evt(4, "running", "程序化过滤无效数据...")
        limit = min(local_count, 200)
        all_jobs = await db.execute(
            f"SELECT id, title, company, salary_min, salary_max, city, url, raw_jd,"
            f" experience, education, company_industry"
            f" FROM jobs{where}"
            f" ORDER BY CASE WHEN raw_jd IS NOT NULL AND raw_jd != '' THEN 0 ELSE 1 END, id DESC"
            f" LIMIT ?",
            tuple(params_list) + (limit,),
        )

        # 加载黑名单
        bl_rows = await db.execute("SELECT company FROM blacklist")
        blacklist = {r["company"] for r in bl_rows}

        filtered, reasons = [], {"无效": 0, "黑名单": 0, "薪资": 0, "城市": 0, "deal_breaker": 0}
        for j in all_jobs:
            if not j.get("title") or not j.get("url"):
                reasons["无效"] += 1
                continue
            if j.get("company") in blacklist:
                reasons["黑名单"] += 1
                continue
            if salary_min and j.get("salary_max") and j["salary_max"] < salary_min:
                reasons["薪资"] += 1
                continue
            if target_cities and j.get("city"):
                if not any(tc in j["city"] for tc in target_cities):
                    reasons["城市"] += 1
                    continue
            # deal_breakers 检查（基于 JD 文本）
            if deal_breakers and j.get("raw_jd"):
                jd_lower = j["raw_jd"].lower()
                hit = False
                for db_item in deal_breakers:
                    if db_item.lower() in jd_lower:
                        hit = True
                        break
                if hit:
                    reasons["deal_breaker"] += 1
                    continue
            filtered.append(j)

        excluded = len(all_jobs) - len(filtered)
        reason_parts = [f"{k} {v}" for k, v in reasons.items() if v > 0]
        filter_detail = f"✅ {len(all_jobs)} → {len(filtered)} 条（排除 {excluded}）"
        if reason_parts:
            filter_detail += f"（{', '.join(reason_parts)}）"
        yield _evt(4, "done", filter_detail)

        if not filtered:
            yield _evt(5, "error", "过滤后无有效岗位，建议放宽条件")
            return

        # ---- Step 5: JD 覆盖率检查 ----
        yield _evt(5, "running", "检查 JD 覆盖率...")
        has_jd = sum(1 for j in filtered if j.get("raw_jd"))
        yield _evt(5, "done", f"✅ {has_jd}/{len(filtered)} 条有 JD")

        # ---- Step 6: 量化匹配（程序化 + LLM） ----
        yield _evt(6, "running", "量化匹配分析...")

        settings = await _load_llm_settings(db)
        api_key = settings.get("llm_api_key")
        if not api_key:
            yield _evt(6, "error", "未配置 API Key，无法进行 AI 匹配")
            return
        base_url = settings.get("llm_base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        model = settings.get("llm_model") or "qwen3.5-flash"

        # 先算程序化维度
        for j in filtered:
            j["_salary_m"] = _calc_salary(salary_min, salary_max, j.get("salary_min"), j.get("salary_max"))
            j["_location_m"] = _calc_location(j.get("city"), target_cities)
            j["_edu_m"] = _calc_edu(user_edu, j.get("education"))
            j["_exp_m"] = _calc_exp(user_years, j.get("experience"))

        # 构建画像摘要
        profile_text = ""
        if resume.get("current_role"):
            profile_text += f"当前职位: {resume['current_role']}\n"
        if user_years:
            profile_text += f"工作年限: {user_years}年\n"
        if skills:
            profile_text += f"技能: {', '.join(skills[:15])}\n"
        if target_roles:
            profile_text += f"目标岗位: {', '.join(target_roles)}\n"
        hl = _j(resume.get("highlights"))
        if hl:
            profile_text += f"核心亮点: {', '.join(hl[:5])}\n"

        # 分批 LLM 评估 skill_score + responsibility_score
        batch_size = 12
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120)
        llm_scores = {}

        for i in range(0, len(filtered), batch_size):
            batch = filtered[i:i + batch_size]
            bn = i // batch_size + 1
            tb = (len(filtered) + batch_size - 1) // batch_size
            yield _evt(6, "running", f"AI 评估中... 第 {bn}/{tb} 批")

            jobs_text = ""
            for j in batch:
                sm, sx = j.get("salary_min") or 0, j.get("salary_max") or 0
                sal = f"{sm}-{sx}K" if sm else "面议"
                snippet = (j["raw_jd"][:300] if j.get("raw_jd") else "")
                jobs_text += f"\n[{j['id']}] {j.get('title','')} | {j.get('company','')} | {sal}"
                if snippet:
                    jobs_text += f"\n  JD: {snippet}"

            prompt = (
                "你是求职匹配分析专家。评估技能匹配度和职责匹配度。\n\n"
                f"## 用户画像\n{profile_text}\n"
                f"## 候选岗位\n{jobs_text}\n\n"
                "输出 JSON 数组（不要其他内容）：\n"
                '[{"id": 岗位ID, "skill_score": 0-100, "resp_score": 0-100, '
                '"missing_skills": ["缺失技能"], "matching_skills": ["匹配技能"], '
                '"reason": "一句话理由"}]'
            )
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                )
                raw = resp.choices[0].message.content.strip()
                if "```" in raw:
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.strip()
                for item in _json.loads(raw):
                    if isinstance(item, dict) and "id" in item:
                        llm_scores[item["id"]] = item
            except Exception:
                pass
            await asyncio.sleep(0.3)

        # 合并 7 维度计算综合分
        # 权重: skill 30%, exp 15%, salary 15%, location 10%, edu 10%, resp 10%, embed 10%
        results = []
        for j in filtered:
            jid = j["id"]
            ls = llm_scores.get(jid, {})
            has_jd_flag = bool(j.get("raw_jd"))
            skill_s = ls.get("skill_score", 40 if not has_jd_flag else 50)
            resp_s = ls.get("resp_score", 50)
            if not has_jd_flag:
                skill_s = min(skill_s, 60)

            overall = round(
                skill_s * 0.30
                + j["_exp_m"] * 0.15
                + j["_salary_m"] * 0.15
                + j["_location_m"] * 0.10
                + j["_edu_m"] * 0.10
                + resp_s * 0.10
                + 50 * 0.10  # embedding_similarity 默认值
            )
            sm, sx = j.get("salary_min") or 0, j.get("salary_max") or 0
            results.append({
                "id": jid,
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "city": j.get("city", ""),
                "salary": f"{sm}-{sx}K" if sm else "面议",
                "url": j.get("url", ""),
                "score": overall,
                "skill_score": skill_s,
                "salary_match": j["_salary_m"],
                "exp_match": j["_exp_m"],
                "reason": ls.get("reason", ""),
                "has_jd": has_jd_flag,
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        top_n = results[:10]

        # 写回 match_score
        for r in results:
            try:
                await db.execute_write("UPDATE jobs SET match_score = ? WHERE id = ?", (r["score"], r["id"]))
            except Exception:
                pass

        yield _evt(6, "done", f"✅ 完成 {len(results)} 条量化匹配", results=top_n)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- Chainlit DataLayer (SQLAlchemy + SQLite) ----

import sqlite3 as _sqlite3

from chainlit.config import config as _cl_config
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

_chainlit_db_path = _project_root / "db" / "chainlit.db"
_chainlit_db_url = f"sqlite+aiosqlite:///{_chainlit_db_path}"

# Create tables
_schema_path = _project_root / "db" / "chainlit_schema.sql"
if _schema_path.exists():
    _conn = _sqlite3.connect(str(_chainlit_db_path))
    _conn.executescript(_schema_path.read_text())
    _conn.close()

# Register before mount_chainlit so get_data_layer() finds it
_cl_config.code.data_layer = lambda: SQLAlchemyDataLayer(conninfo=_chainlit_db_url)

# Also eagerly initialize to prevent race with lazy init
import chainlit.data as _cl_data

_cl_data._data_layer = SQLAlchemyDataLayer(conninfo=_chainlit_db_url)
_cl_data._data_layer_initialized = True

# ---- 挂载 Chainlit ----

mount_chainlit(app=app, target=str(Path(__file__).parent / "chat.py"), path="/chat")
