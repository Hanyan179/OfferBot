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
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from chainlit.utils import mount_chainlit

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config import load_config
from db.database import Database
from web.resume_service import ResumeService

app = FastAPI(title="Boss Agent")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

PROVIDER_PRESETS = {
    "dashscope": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.6-plus"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": "gemini-2.5-flash"},
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
        "SELECT id, url, title, company, salary_min, salary_max, city, match_score "
        "FROM jobs ORDER BY match_score DESC NULLS LAST, id DESC"
    )
    return [
        {
            "title": r.get("title") or "未知岗位",
            "company": r.get("company") or "未知公司",
            "salary": _format_salary(r.get("salary_min"), r.get("salary_max")),
            "city": r.get("city") or "",
            "score": round(r["match_score"]) if r.get("match_score") is not None else 0,
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

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


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
        # 关闭思考模式加速测试（千问 Qwen3 系列默认开启 thinking）
        response = await client.chat(
            [{"role": "user", "content": "你好，请用一句话回复"}],
            extra_body={"enable_thinking": False},
        )
        return JSONResponse({"ok": True, "response": response[:200]})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ---- Resume API ----

@app.put("/api/resume")
async def api_update_resume(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "请求格式错误"}, status_code=400)
    try:
        db = await _get_db()
        svc = ResumeService(db)
        result = await svc.update_resume(body)
        return JSONResponse({"ok": True, "fields": result.get("fields", [])})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"保存失败: {e}"}, status_code=500)


@app.get("/api/resume/export/docx")
async def api_export_docx():
    try:
        db = await _get_db()
        svc = ResumeService(db)
        docx_bytes, filename = await svc.export_docx()
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"导出失败: {e}"}, status_code=500)

    import io
    from urllib.parse import quote

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


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
    gen_config = gtypes.GenerateContentConfig(
        tools=[tools],
        system_instruction="你是 OfferBot，一个专业的 AI 求职顾问。根据用户请求，调用合适的工具或直接回复。",
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

    try:
        for turn in range(max_turns):
            import asyncio
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=contents,
                config=gen_config,
            )

            candidate = response.candidates[0]
            parts = candidate.content.parts

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
                        result = await tool.execute(tool_args, context={"db": db})
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
        return JSONResponse(
            {"ok": False, "error": f"Agent 执行失败: {e}"},
            status_code=500,
        )

    total_duration_ms = int((time.time() - start_time) * 1000)
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


# ---- 对话管理 API ----

def _get_conversation_manager():
    """获取 ConversationManager 实例（懒初始化，缓存在 app.state 上）。"""
    if not hasattr(app.state, "conversation_manager") or app.state.conversation_manager is None:
        from agent.conversation_manager import ConversationManager
        from tools.data.chat_history import ChatHistoryStore
        store = ChatHistoryStore()
        app.state.conversation_manager = ConversationManager(store)
    return app.state.conversation_manager


@app.get("/api/conversations")
async def api_list_conversations():
    try:
        mgr = _get_conversation_manager()
        conversations = await mgr.list_conversations()
        return JSONResponse({"conversations": conversations})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/conversations")
async def api_create_conversation():
    try:
        mgr = _get_conversation_manager()
        conversation = await mgr.create_conversation()
        return JSONResponse(conversation)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/conversations/{conversation_id}/messages")
async def api_get_conversation_messages(conversation_id: str):
    try:
        mgr = _get_conversation_manager()
        messages = await mgr.get_conversation_messages(conversation_id)
        return JSONResponse({"messages": messages})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.delete("/api/conversations/{conversation_id}")
async def api_delete_conversation(conversation_id: str):
    try:
        mgr = _get_conversation_manager()
        # 如果删除的是活跃对话，先创建新对话
        active_id = await mgr._store.get_active_conversation_id()
        if active_id == conversation_id:
            new_conv = await mgr.create_conversation()
            # 如果新对话 ID 与待删除 ID 相同（同一秒内），跳过删除
            if new_conv["id"] == conversation_id:
                return JSONResponse({"ok": True})
        success = await mgr.delete_conversation(conversation_id)
        if success:
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": False, "error": "删除失败"}, status_code=500)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---- 挂载 Chainlit ----

mount_chainlit(app=app, target=str(Path(__file__).parent / "chat.py"), path="/chat")
