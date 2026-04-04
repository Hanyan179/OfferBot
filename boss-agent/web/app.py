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
    "dashscope": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.5-flash"},
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
    if not rows:
        return {"name": None, "city": None, "experience": None, "education": None, "tech_stack": [], "work_experience": []}

    row = rows[0]
    # Build experience string from years_of_experience
    years = row.get("years_of_experience")
    experience_str = f"{years}年" if years is not None else row.get("current_role")

    # Parse JSON fields
    skills_flat = _safe_json_load(row.get("skills_flat")) or []
    tech_stack_dict = _safe_json_load(row.get("tech_stack"))
    # Flatten tech_stack dict into a list if it's a dict, otherwise use skills_flat
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
            })

    return {
        "name": row.get("name"),
        "city": row.get("city"),
        "experience": experience_str,
        "education": row.get("education_level"),
        "tech_stack": tech_stack,
        "work_experience": work_experience,
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
                body_lines.append(bline)

            entries.append({
                "title": title,
                "body_html": "\n".join(body_lines).strip(),
                "source_id": source_id,
                "extracted_at": extracted_at,
            })

        categories.append({"display_name": display_name, "entries": entries})

    return categories


@app.get("/page/memory", response_class=HTMLResponse)
async def page_memory(request: Request):
    memory_dir = _project_root / "data" / "记忆画像"
    categories = _parse_memory_files(memory_dir)
    return templates.TemplateResponse(request, "embed_wrap.html", {
        "title": "记忆画像", "content_template": "memory_content.html",
        "categories": categories,
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


# ---- 挂载 Chainlit ----

mount_chainlit(app=app, target=str(Path(__file__).parent / "chat.py"), path="/chat")
