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
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from chainlit.utils import mount_chainlit

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


# ---- 阶段标签映射 ----

STAGE_LABELS: dict[str, str] = {
    "applied": "已投递", "viewed": "已读", "replied": "已回复",
    "interview_scheduled": "约面试", "round_1": "一面", "round_2": "二面",
    "round_3": "三面", "hr_round": "HR面", "offer": "Offer",
    "rejected": "已拒绝", "withdrawn": "已放弃",
}

# 终态阶段
_TERMINAL_STAGES = {"offer", "rejected", "withdrawn"}

# 面试进行中阶段（用于颜色判断）
_INTERVIEW_ACTIVE = {"interview_scheduled", "round_1", "round_2", "round_3", "hr_round"}


def _format_salary(salary_min: int | None, salary_max: int | None) -> str:
    if salary_min and salary_max:
        return f"{salary_min}-{salary_max}K"
    if salary_min:
        return f"{salary_min}K+"
    if salary_max:
        return f"{salary_max}K"
    return "面议"


def _stage_color(stage: str) -> str:
    if stage == "offer":
        return "green"
    if stage in _TERMINAL_STAGES:
        return "red"
    if stage in _INTERVIEW_ACTIVE:
        return "green"
    return "yellow"


def _relative_time(ts: str | None) -> str:
    """将 ISO 时间戳转为相对时间描述。"""
    if not ts:
        return ""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if isinstance(ts, str) else ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        days = delta.days
        if days == 0:
            return "今天"
        if days == 1:
            return "昨天"
        if days < 7:
            return f"{days}天前"
        if days < 30:
            return f"{days // 7}周前"
        return f"{days // 30}月前"
    except (ValueError, TypeError):
        return str(ts)[:10] if ts else ""


async def _load_jobs(db: Database) -> list[dict]:
    """从 jobs 表加载岗位列表，格式化给模板使用。"""
    rows = await db.execute(
        "SELECT id, url, title, company, salary_min, salary_max, city "
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
        }
        for r in rows
    ]


async def _load_interviews(db: Database) -> tuple[list[dict], list[dict]]:
    """加载面试漏斗数据和面试列表。返回 (funnel, interviews)。"""
    # 漏斗数据
    rows = await db.execute("SELECT COUNT(*) AS cnt FROM applications")
    total = rows[0]["cnt"]

    funnel_stages = [
        ("投递", "applied"), ("已读", "viewed"), ("回复", "replied"),
        ("面试", "interview_scheduled"), ("Offer", "offer"),
    ]
    funnel = []
    for label, stage in funnel_stages:
        if stage == "applied":
            funnel.append({"name": label, "count": total})
        else:
            r = await db.execute(
                "SELECT COUNT(DISTINCT application_id) AS cnt "
                "FROM interview_stage_log WHERE to_stage = ?", (stage,)
            )
            funnel.append({"name": label, "count": r[0]["cnt"]})

    # 面试列表：每个投递的最新状态
    interviews_raw = await db.execute(
        "SELECT a.id AS app_id, j.title, j.company, "
        "COALESCE(it.stage, 'applied') AS stage, "
        "COALESCE(it.stage_changed_at, a.created_at) AS updated "
        "FROM applications a "
        "JOIN jobs j ON a.job_id = j.id "
        "LEFT JOIN interview_tracking it ON it.application_id = a.id "
        "ORDER BY COALESCE(it.stage_changed_at, a.created_at) DESC"
    )
    interviews = [
        {
            "title": r.get("title") or "未知岗位",
            "company": r.get("company") or "未知公司",
            "stage": r["stage"],
            "stage_label": STAGE_LABELS.get(r["stage"], r["stage"]),
            "updated": _relative_time(r.get("updated")),
        }
        for r in interviews_raw
    ]

    return funnel, interviews


async def _load_overview(db: Database) -> dict:
    """加载总览/徽章墙数据。"""
    # 统计数据
    rows = await db.execute("SELECT COUNT(*) AS cnt FROM applications")
    total = rows[0]["cnt"]

    # 非终态 = 进行中
    active_rows = await db.execute(
        "SELECT COUNT(*) AS cnt FROM applications a "
        "LEFT JOIN interview_tracking it ON it.application_id = a.id "
        "WHERE COALESCE(it.stage, 'applied') NOT IN ('offer', 'rejected', 'withdrawn')"
    )
    active = active_rows[0]["cnt"]

    # 本周新增投递
    week_rows = await db.execute(
        "SELECT COUNT(*) AS cnt FROM applications "
        "WHERE created_at >= date('now', '-7 days')"
    )
    new_this_week = week_rows[0]["cnt"]

    # 面试中（interview_scheduled 及之后的面试阶段）
    interview_rows = await db.execute(
        "SELECT COUNT(DISTINCT application_id) AS cnt FROM interview_tracking "
        "WHERE stage IN ('interview_scheduled','round_1','round_2','round_3','hr_round')"
    )
    interviews_count = interview_rows[0]["cnt"]

    # Offer 数
    offer_rows = await db.execute(
        "SELECT COUNT(DISTINCT application_id) AS cnt FROM interview_tracking "
        "WHERE stage = 'offer'"
    )
    offers = offer_rows[0]["cnt"]

    stats = {
        "active": active,
        "new_this_week": new_this_week,
        "interviews": interviews_count,
        "offers": offers,
    }

    # 徽章墙卡片
    cards_raw = await db.execute(
        "SELECT j.title, j.company, j.match_score, "
        "COALESCE(it.stage, 'applied') AS stage "
        "FROM applications a "
        "JOIN jobs j ON a.job_id = j.id "
        "LEFT JOIN interview_tracking it ON it.application_id = a.id "
        "ORDER BY COALESCE(it.stage_changed_at, a.created_at) DESC"
    )
    cards = [
        {
            "title": r.get("title") or "未知岗位",
            "company": r.get("company") or "未知公司",
            "score": f"{round(r['match_score'])}%" if r.get("match_score") is not None else "N/A",
            "stage": STAGE_LABELS.get(r["stage"], r["stage"]),
            "color": _stage_color(r["stage"]),
        }
        for r in cards_raw
    ]

    return {"stats": stats, "cards": cards}


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
    return templates.TemplateResponse(request, "settings_embed.html", {
        "provider": settings.get("llm_provider") or "dashscope",
        "api_key": settings.get("llm_api_key") or config.dashscope_api_key,
        "base_url": settings.get("llm_base_url") or config.api_base_url,
        "model": settings.get("llm_model") or config.dashscope_llm_model,
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


@app.get("/page/interviews", response_class=HTMLResponse)
async def page_interviews(request: Request):
    db = await _get_db()
    funnel, interviews = await _load_interviews(db)
    return templates.TemplateResponse(request, "embed_wrap.html", {
        "title": "面试追踪", "content_template": "interviews_content.html",
        "funnel": funnel, "interviews": interviews,
    })


@app.get("/page/overview", response_class=HTMLResponse)
async def page_overview(request: Request):
    db = await _get_db()
    overview = await _load_overview(db)
    return templates.TemplateResponse(request, "embed_wrap.html", {
        "title": "求职总览", "content_template": "overview_content.html",
        **overview,
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
        # enable_thinking 等厂商参数由 LLMClient._apply_provider_defaults 自动处理
        response = await client.chat(
            [{"role": "user", "content": "你好，请用一句话回复"}],
        )
        return JSONResponse({"ok": True, "response": response[:200]})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ---- 健康检查 ----

@app.get("/api/health")
async def api_health():
    return {"status": "ok"}


# ---- 测试 API ----

@app.post("/api/test/chat")
async def api_test_chat(request: Request):
    """
    通用 Agent 对话测试接口。

    使用 google-genai SDK 直接调用 Gemini，独立于主体 LLMClient。
    自行管理 function calling 循环，收集完整执行过程并返回结构化报告。
    通过 config.enable_test_api 控制开关，生产环境可关闭。
    """
    import json as _json
    import time

    config = load_config()
    if not config.enable_test_api:
        return JSONResponse(
            {"ok": False, "error": "测试 API 未启用"},
            status_code=403,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"ok": False, "error": "请求格式错误"},
            status_code=400,
        )

    message = body.get("message", "").strip()
    if not message:
        return JSONResponse(
            {"ok": False, "error": "message 不能为空"},
            status_code=400,
        )

    conversation_id = body.get("conversation_id")
    history = body.get("history") or []

    # 初始化
    db = await _get_db()
    llm_settings = await _load_llm_settings(db)
    api_key = llm_settings.get("llm_api_key", "")
    model = body.get("model") or "gemini-3-flash-preview"

    if not api_key:
        return JSONResponse(
            {"ok": False, "error": "未配置 API Key，请先在设置中配置"},
            status_code=400,
        )

    # 构建 tool registry 和 tool 定义
    from agent.bootstrap import create_tool_registry
    registry, _skill_loader = create_tool_registry()

    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        return JSONResponse(
            {"ok": False, "error": "google-genai SDK 未安装"},
            status_code=500,
        )

    import httpx as _httpx
    _proxy_url = "http://127.0.0.1:7893"
    _http_client = _httpx.Client(proxy=_proxy_url, timeout=60)
    client = genai.Client(
        api_key=api_key,
        http_options={"httpxClient": _http_client},
    )

    # 将 ToolRegistry 的 schemas 转为 google-genai 格式
    func_decls = []
    for schema in registry.get_all_schemas():
        fn = schema["function"]
        func_decls.append({
            "name": fn["name"],
            "description": fn["description"],
            "parameters": fn["parameters"],
        })

    tools = gtypes.Tool(function_declarations=func_decls)
    from agent.system_prompt import build_full_system_prompt
    gen_config = gtypes.GenerateContentConfig(
        tools=[tools],
        system_instruction=build_full_system_prompt(),
    )

    # 构建对话内容
    contents = []
    for h in history:
        if isinstance(h, dict) and "role" in h and "content" in h:
            role = "model" if h["role"] == "assistant" else "user"
            contents.append(gtypes.Content(
                role=role,
                parts=[gtypes.Part(text=h["content"])],
            ))
    contents.append(gtypes.Content(
        role="user",
        parts=[gtypes.Part(text=message)],
    ))

    # Agent loop: LLM → tool call → execute → feed back → repeat
    tool_calls_report: list[dict] = []
    reply = ""
    start_time = time.time()
    max_turns = 10

    # --- 对话日志 ---
    from tools.data.conversation_logger import ConversationLogger
    conv_log_id = conversation_id or f"test-{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"
    conv_logger = ConversationLogger(conv_log_id)
    conv_logger.begin_turn(message)

    try:
        for turn in range(max_turns):
            import asyncio
            conv_logger.log_llm_request(model=model, message_count=len(contents), has_tools=True)
            llm_start = time.time()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=contents,
                config=gen_config,
            )

            candidate = response.candidates[0]
            parts = candidate.content.parts
            llm_ms = int((time.time() - llm_start) * 1000)

            # 收集 function calls 和 text
            func_calls_in_turn = []
            text_parts = []
            for part in parts:
                if part.function_call:
                    func_calls_in_turn.append(part.function_call)
                elif part.text:
                    text_parts.append(part.text)

            if text_parts:
                reply = "\n".join(text_parts)

            conv_logger.log_llm_response(
                has_text=bool(text_parts),
                tool_call_count=len(func_calls_in_turn),
                duration_ms=llm_ms,
            )

            # 没有 function call，结束
            if not func_calls_in_turn:
                break

            # 把 model 的响应加入 contents
            contents.append(candidate.content)

            # 执行每个 function call
            func_response_parts = []
            for fc in func_calls_in_turn:
                tool_name = fc.name
                tool_args = dict(fc.args) if fc.args else {}
                tool_start = time.time()

                conv_logger.log_tool_start(tool_name, tool_args)
                print(f"[TEST_CHAT] Tool call: {tool_name}({_json.dumps(tool_args, ensure_ascii=False)[:100]})", flush=True)

                # 执行 tool
                tool = registry.get_tool(tool_name)
                tc_report = {
                    "name": tool_name,
                    "display_name": registry.get_display_name(tool_name),
                    "params": tool_args,
                    "result": None,
                    "success": False,
                    "duration_ms": 0,
                }

                if tool:
                    try:
                        # 构建完整 context（包含 getjob_client 和 task_monitor）
                        from services.getjob_client import GetjobClient
                        from services.task_monitor import TaskMonitor
                        from rag.job_rag import JobRAG
                        _getjob_client = GetjobClient()
                        _task_monitor = TaskMonitor()

                        # JobRAG 实例缓存在 app.state
                        if not hasattr(app.state, "job_rag") or app.state.job_rag is None:
                            _job_rag = JobRAG(
                                working_dir=str(_project_root / "data" / "lightrag_jobs"),
                                api_key=api_key,
                                base_url=llm_settings.get("llm_base_url", ""),
                                model=llm_settings.get("llm_model", ""),
                                db=db,
                            )
                            try:
                                await _job_rag.initialize()
                            except Exception as _e:
                                import logging
                                logging.getLogger(__name__).warning("测试接口 JobRAG 初始化失败: %s", _e)
                            app.state.job_rag = _job_rag

                        _tool_context = {
                            "db": db,
                            "getjob_client": _getjob_client,
                            "task_monitor": _task_monitor,
                            "agent_busy_check": lambda: False,
                            "job_rag": app.state.job_rag,
                        }
                        result = await tool.execute(tool_args, context=_tool_context)
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
                conv_logger.log_tool_result(
                    tool_name,
                    success=tc_report["success"],
                    duration_ms=tc_report["duration_ms"],
                    result_preview=tc_report["result"] or "",
                )

                print(f"[TEST_CHAT]   -> {'✅' if tc_report['success'] else '❌'} {tc_report['duration_ms']}ms", flush=True)

                # 构建 function response
                func_response_parts.append(
                    gtypes.Part.from_function_response(
                        name=tool_name,
                        response={"result": result_str},
                    )
                )

            # 把 function responses 加入 contents
            contents.append(gtypes.Content(
                role="user",
                parts=func_response_parts,
            ))

    except Exception as e:
        import traceback
        print(f"[TEST_CHAT] EXCEPTION: {e}", flush=True)
        traceback.print_exc()
        conv_logger.log_llm_error(str(e))
        conv_logger.end_turn(f"ERROR: {e}")
        return JSONResponse(
            {"ok": False, "error": f"Agent 执行失败: {e}"},
            status_code=500,
        )

    total_duration_ms = int((time.time() - start_time) * 1000)
    conv_logger.end_turn(reply or "(no reply)")
    print(f"[TEST_CHAT] Done. reply={reply[:80] if reply else '(empty)'}, tools={len(tool_calls_report)}, {total_duration_ms}ms", flush=True)

    return JSONResponse({
        "ok": True,
        "reply": reply,
        "tool_calls": tool_calls_report,
        "conversation_id": conversation_id or "",
        "total_duration_ms": total_duration_ms,
        "model": model,
        "token_usage": {"prompt": 0, "completion": 0},
    })


# ---- 任务状态 API（供前端任务面板轮询） ----

@app.get("/api/tasks")
async def api_get_tasks():
    """返回当前活跃的任务列表（运行中 + 最近完成的）"""
    from services.task_state import TaskStateStore
    store = TaskStateStore.get()
    return JSONResponse({"tasks": store.get_active()})


@app.get("/api/jobs")
async def api_list_jobs(
    page: int = 1,
    size: int = 20,
    city: str = "",
    keyword: str = "",
    salary_min: int = 0,
    has_jd: bool = False,
):
    """岗位列表 API，支持分页和筛选"""
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
        conditions.append("(salary_max >= ? OR salary_max IS NULL)")
        params.append(salary_min)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    # 总数
    count_rows = await db.execute(f"SELECT COUNT(*) as cnt FROM jobs{where}", tuple(params))
    total = count_rows[0]["cnt"] if count_rows else 0

    # 分页数据
    offset = (page - 1) * size
    rows = await db.execute(
        f"SELECT id, url, title, company, salary_min, salary_max, city, match_score FROM jobs{where} ORDER BY id DESC LIMIT ? OFFSET ?",
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


# ---- 知识图谱 API ----

@app.get("/api/graph/user")
async def api_graph_user():
    import sqlite3
    from web.graph_api import build_user_graph
    conn = sqlite3.connect(load_config().db_path)
    return build_user_graph(conn)

@app.get("/api/graph/jobs")
async def api_graph_jobs():
    from web.graph_api import build_jobs_graph
    return build_jobs_graph(str(Path(__file__).parent.parent / "data" / "lightrag_jobs"))

@app.get("/api/graph/match")
async def api_graph_match():
    """岗位匹配度排行（embedding + 门槛过滤）"""
    import sqlite3 as _sql, json as _json, os as _os, re as _re
    import numpy as _np
    from google import genai as _genai

    _conn = _sql.connect(load_config().db_path)
    _conn.row_factory = lambda c,r: {col[0]:r[i] for i,col in enumerate(c.description)}

    _resume = _conn.execute("SELECT * FROM resumes WHERE is_active=1").fetchone()
    if not _resume or not _resume.get("raw_text"):
        return {"matches": [], "error": "请先上传简历"}

    _prefs = _conn.execute("SELECT * FROM job_preferences WHERE is_active=1").fetchone()
    _user_skills = _json.loads(_resume.get("skills_flat") or "[]")
    _salary_min = (_prefs or {}).get("salary_min") or 0

    # 有 JD 的岗位
    _jobs = _conn.execute(
        "SELECT id, title, company, city, salary_min, salary_max, experience, education, url, raw_jd "
        "FROM jobs WHERE raw_jd IS NOT NULL AND raw_jd != ''"
    ).fetchall()
    if not _jobs:
        return {"matches": [], "user_skills": _user_skills}

    # embedding 匹配
    _api_key = _conn.execute("SELECT value FROM user_preferences WHERE key='llm_api_key'").fetchone()
    if not _api_key:
        return {"matches": [], "error": "未配置 API Key"}

    _client = _genai.Client(api_key=_api_key["value"])
    _user_text = f"{_resume.get('summary','')}\n技能: {', '.join(_user_skills)}\n{(_resume.get('raw_text') or '')[:2000]}"
    _texts = [_user_text] + [f"{j['title']}\n{j['company']}\n{j['raw_jd']}" for j in _jobs]

    _resp = _client.models.embed_content(model="gemini-embedding-001", contents=[t[:8000] for t in _texts])
    _embs = _np.array([e.values for e in _resp.embeddings], dtype=_np.float32)
    _embs /= _np.linalg.norm(_embs, axis=1, keepdims=True)
    _scores = _embs[1:] @ _embs[0]

    _user_skills_lower = set(s.lower() for s in _user_skills)
    _matches = []
    for i, job in enumerate(_jobs):
        _jd = (job.get("raw_jd") or "").lower()
        # 门槛
        _blocked = []
        if any(kw in _jd for kw in ["硕士", "研究生", "master"]):
            if _resume.get("education_level") in ["本科", "大专"]:
                _blocked.append("学历要求硕士")
        if any(kw in _jd for kw in ["985", "211", "双一流"]):
            _blocked.append("要求985/211")

        # 薪资过滤
        _sal_low = ""
        _job_sal_max = job.get("salary_max") or 0
        if _salary_min and _job_sal_max and _job_sal_max < _salary_min * 0.8:
            _sal_low = "薪资偏低"

        # 技能加分
        _skill_bonus = sum(0.01 for s in _user_skills_lower if s in _jd)
        _matched_skills = [s for s in _user_skills if s.lower() in _jd]
        _final = float(_scores[i]) + _skill_bonus

        _sal_text = f"{job.get('salary_min','?')}-{job.get('salary_max','?')}K"
        _matches.append({
            "name": job["title"],
            "company": job.get("company", ""),
            "salary": _sal_text,
            "city": job.get("city", ""),
            "url": job.get("url", ""),
            "match_rate": round(_final, 3),
            "base_score": round(float(_scores[i]), 3),
            "matched_skills": _matched_skills,
            "blocked": _blocked,
            "salary_warning": _sal_low,
        })

    _matches.sort(key=lambda x: x["match_rate"], reverse=True)
    return {"matches": _matches, "user_skills": _user_skills}

@app.get("/graph")
async def graph_page():
    """知识图谱可视化页面"""
    from fastapi.responses import FileResponse
    return FileResponse(
        str(Path(__file__).parent / "static" / "graph.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )

@app.get("/job/{job_id}")
async def job_detail_page(job_id: int):
    from fastapi.responses import FileResponse
    return FileResponse(
        str(Path(__file__).parent / "static" / "job_detail.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ---- 挂载 Chainlit ----

mount_chainlit(app=app, target=str(Path(__file__).parent / "chat.py"), path="/chat")
