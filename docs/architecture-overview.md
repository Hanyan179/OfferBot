# OfferBot 架构全景文档

> 最后更新: 2026-04-06

## 一、项目定位

OfferBot 是一个 AI 求职顾问 Agent，帮助用户从认识自己到拿到 offer 的全流程。核心能力包括：岗位发现与筛选、简历匹配分析、面试追踪、打招呼语生成、记忆画像管理。

---

## 二、整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户层 (Browser)                         │
│  http://localhost:7860                                          │
│  ┌──────────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ /chat (对话)  │  │ /settings│  │ /jobs    │  │ /overview  │  │
│  │ Chainlit UI  │  │ 设置页面  │  │ 岗位列表  │  │ 数据总览   │  │
│  └──────┬───────┘  └──────────┘  └──────────┘  └────────────┘  │
└─────────┼───────────────────────────────────────────────────────┘
          │ WebSocket (Chainlit)
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Web 层 (FastAPI + Chainlit)                  │
│  boss-agent/web/                                                │
│  ┌──────────────┐  ┌──────────────────────────────────────────┐ │
│  │ app.py       │  │ chat.py                                  │ │
│  │ FastAPI 路由  │  │ Chainlit 对话逻辑                        │ │
│  │ REST API     │  │ on_chat_start → on_message → events      │ │
│  └──────────────┘  └──────────────┬───────────────────────────┘ │
└────────────────────────────────────┼────────────────────────────┘
                                     │ 调用
                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Agent 核心引擎层                              │
│  boss-agent/agent/                                              │
│                                                                 │
│  ┌────────────┐    ┌────────────────────────────────────────┐   │
│  │ bootstrap  │───▶│ 初始化: Registry + Planner + Executor  │   │
│  └────────────┘    │ + Browser + SkillLoader + RAG          │   │
│                    └────────────────────────────────────────┘   │
│                                                                 │
│  ┌────────────┐    ┌────────────┐    ┌────────────────────┐    │
│  │  Planner   │    │  Executor  │    │ MemoryExtractor    │    │
│  │ 意图→计划   │    │ ReAct Loop │    │ 记忆提取子Agent     │    │
│  └────────────┘    └─────┬──────┘    └────────────────────┘    │
│                          │                                      │
│  ┌────────────┐    ┌─────▼──────┐    ┌────────────────────┐    │
│  │   State    │    │ LLMClient  │    │   SkillLoader      │    │
│  │ 不可变状态  │    │ OpenAI兼容  │    │ 场景剧本加载器      │    │
│  └────────────┘    └────────────┘    └────────────────────┘    │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              ToolRegistry (工具注册中心)                 │    │
│  │  register() → get_tool() → get_all_schemas()           │    │
│  └────────────────────────┬───────────────────────────────┘    │
└───────────────────────────┼─────────────────────────────────────┘
                            │ 调用
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Tool 层 (30+ 工具)                        │
│  boss-agent/tools/                                              │
│                                                                 │
│  ┌─ data/ ──────────────────────────────────────────────────┐   │
│  │ query_jobs, search_jobs, save_job, job_manage            │   │
│  │ application_store, interview_tracker, stats              │   │
│  │ memory_tools (save/get/search/update/delete/cognitive)   │   │
│  │ user_profile, blacklist, export, chat_history            │   │
│  │ execution_trace, conversation_logger                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ getjob/ ────────────────────────────────────────────────┐   │
│  │ platform_status, platform_control (start/stop)           │   │
│  │ platform_config, platform_sync, platform_stats           │   │
│  │ platform_deliver, fetch_detail, service_manager          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ browser/ ───────────┐  ┌─ ai/ ─────────────────────────┐   │
│  │ web_fetch, web_search│  │ get_skill_content              │   │
│  └──────────────────────┘  └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
          │                              │
          ▼                              ▼
┌──────────────────┐    ┌─────────────────────────────────────────┐
│   数据持久层      │    │          外部服务                        │
│                  │    │                                         │
│ ┌──────────────┐ │    │ ┌─────────────────────────────────────┐ │
│ │ SQLite (WAL) │ │    │ │ Playwright 浏览器自动化              │ │
│ │ boss_agent.db│ │    │ │ 猎聘岗位爬取 + JD 获取 + 投递        │ │
│ └──────────────┘ │    │ └─────────────────────────────────────┘ │
│ ┌──────────────┐ │    │                                         │
│ │ 记忆文件系统  │ │    │ ┌─────────────────────────────────────┐ │
│ │ data/记忆画像/│ │    │ │ LLM API (OpenAI 兼容)              │ │
│ │ *.md 文件    │ │    │ │ DashScope / OpenAI / Gemini /      │ │
│ └──────────────┘ │    │ │ DeepSeek                            │ │
│                  │    │ └─────────────────────────────────────┘ │
│ ┌──────────────┐ │    │                                         │
│ │ JSONL 对话   │ │    │ ┌─────────────────────────────────────┐ │
│ │ data/conver- │ │    │ │ FAISS 向量索引                      │ │
│ │ sations/     │ │    │ │ 岗位语义检索                         │ │
│ └──────────────┘ │    │ └─────────────────────────────────────┘ │
└──────────────────┘    └─────────────────────────────────────────┘
```

---

## 三、启动流程

### 3.1 应用启动

```
scripts/start-dev.sh
  ├── 1. 清理残留 tmux 会话
  ├── 2. 启动 getjob 服务 (Java, port 8888)
  ├── 3. 启动 OfferBot (uvicorn web.app:app, port 7860)
  └── 4. 创建 iTerm2 6 窗格布局
```

### 3.2 Agent 初始化链 (chat.py → bootstrap.py)

```
on_chat_start()
  │
  ├── 1. load_config() — 从环境变量读取配置
  ├── 2. Database.connect() + init_schema() — SQLite 连接
  ├── 3. ChatHistoryStore / ExecutionTraceStore — 对话持久化
  ├── 4. _load_llm_config(db) — 从 DB 读 LLM 配置
  │
  ├── 5. bootstrap(db, api_key, model, base_url)
  │      ├── create_tool_registry() — 注册 30+ Tool
  │      ├── LLMClient(api_key, model, base_url)
  │      ├── LiepinBrowser() — Playwright 浏览器自动化
  │      ├── JobVectorIndex().load()
  │      ├── Planner(registry, llm_client)
  │      ├── Executor(registry, llm_client)
  │      └── SkillLoader(registry)
  │
  ├── 6. TaskMonitor() — 后台任务监控
  ├── 7. SkillLoader.to_prompt_section() — Skills 注入
  ├── 8. build_full_system_prompt() — 拼接完整 System Prompt
  ├── 9. 加载用户档案 + 记忆画像 → 注入对话历史
  └── 10. 显示欢迎语
```

---

## 四、核心执行流程

### 4.1 用户消息处理 (主流程)

```
用户输入消息
  │
  ▼
on_message(message)
  ├── 解析附件 (PDF/DOCX/MD → 文本)
  └── handle_user_message(content)
        │
        ├── 1. 追加到 chat_history
        ├── 2. 持久化到 JSONL
        ├── 3. 创建 ConversationLogger
        │
        ├── 4. executor.chat(messages, context, system_prompt)
        │      │
        │      │  ┌─────────── ReAct Loop (最多 max_turns 轮) ──────────┐
        │      │  │                                                      │
        │      │  │  ① LLM 调用 (chat_with_tools)                       │
        │      │  │     ├── 传入: system_prompt + 对话历史 + 工具定义     │
        │      │  │     └── 返回: 文本回复 + tool_calls                  │
        │      │  │                                                      │
        │      │  │  ② 如果有 reasoning_content → yield thinking event   │
        │      │  │  ③ 如果有 text_content → yield assistant_message     │
        │      │  │  ④ 如果无 tool_calls → 结束循环                      │
        │      │  │                                                      │
        │      │  │  ⑤ 执行每个 tool_call:                               │
        │      │  │     ├── yield tool_start event                       │
        │      │  │     ├── _execute_tool(call, context, max_retries=3)  │
        │      │  │     │   └── 指数退避重试: 2s → 4s → 8s               │
        │      │  │     ├── yield tool_result event                      │
        │      │  │     └── 工具结果追加到 full_messages                  │
        │      │  │                                                      │
        │      │  │  ⑥ drain TaskMonitor 通知队列                        │
        │      │  │     └── 后台任务完成通知注入到消息历史                 │
        │      │  │                                                      │
        │      │  │  turn++ → 回到 ①                                     │
        │      │  └──────────────────────────────────────────────────────┘
        │      │
        │      └── yield 各种 AgentEvent 给 UI 层
        │
        ├── 5. UI 层处理 events:
        │      ├── thinking → 折叠展示思考过程
        │      ├── assistant_message → 直接展示
        │      ├── tool_start → 创建 Step UI
        │      ├── tool_result → 更新 Step 结果
        │      ├── error → 错误提示
        │      ├── task_notification → 后台任务通知
        │      └── max_turns_reached → 警告
        │
        ├── 6. 持久化 assistant 回复到 JSONL
        ├── 7. 保存执行轨迹 (ExecutionTraceStore)
        └── 8. 标记 _conv_has_interaction = True
```

### 4.2 记忆提取 (异步子 Agent)

```
触发时机: 新建对话时，检查上一轮对话是否已提取记忆

_launch_memory_extraction(history, conversation_id)
  │
  └── asyncio.create_task(_run_extraction(...))
        │
        └── MemoryExtractor.extract(recent_messages, context)
              │
              ├── 1. 预读已有记忆摘要 (get_user_cognitive_model)
              ├── 2. 构建提取 Prompt (对话内容 + 分类列表 + 已有记忆)
              │
              ├── 3. 多轮工具调用循环 (最多 5 轮):
              │      ├── LLM chat_with_tools (独立调用，不影响主对话)
              │      ├── 执行 tool_calls:
              │      │   ├── get_memory → 查看已有记忆
              │      │   ├── save_memory → 新增记忆
              │      │   ├── update_memory → 更新已有记忆
              │      │   └── delete_memory → 删除重复记忆
              │      └── 工具结果反馈给 LLM → 继续决策
              │
              └── 4. 标记 .extracted (防止重复提取)
```

---

## 五、模块详解

### 5.1 Agent 核心 (`boss-agent/agent/`)

| 文件 | 职责 |
|------|------|
| `bootstrap.py` | 应用启动引导，注册所有 Tool，创建核心组件 |
| `executor.py` | ReAct Agent Loop 执行器，系统心脏。`chat()` 方法实现对话模式，`agent_loop()` 实现计划模式 |
| `planner.py` | 意图理解与任务拆解，将自然语言转为 ExecutionPlan（目前主流程用 chat 模式，planner 备用） |
| `state.py` | 不可变状态数据结构：AgentState, ExecutionPlan, PlanStep, ToolCall, ToolResult, AgentEvent 等 |
| `tool_registry.py` | Tool 抽象基类 + ToolRegistry 注册中心，统一管理工具的注册、发现、调用 |
| `llm_client.py` | OpenAI 兼容格式的 LLM 客户端，支持 DashScope/OpenAI/Gemini/DeepSeek，自动适配厂商参数 |
| `system_prompt.py` | Agent 人设 + 行为准则 + 工具使用策略 + 记忆系统指引 + Skills 注入 |
| `memory_extractor.py` | 记忆提取子 Agent，对话结束后异步提取用户信息写入记忆文件 |
| `memory.py` | 持久记忆模块（用户偏好、黑名单、投递历史的 DB 操作） |
| `skill_loader.py` | Skills 加载器，扫描 `skills/` 文件夹，解析 SKILL.md，生成 System Prompt 注入段 |
| `conversation_manager.py` | 对话管理器，封装对话的创建、列表、切换、删除 |
| `report.py` | 执行报告生成，任务完成后输出结构化报告 |

### 5.2 Tool 层 (`boss-agent/tools/`)

#### Data Tools (本地数据操作)
| Tool | 功能 |
|------|------|
| `query_jobs` | 多条件查询本地岗位库 |
| `search_jobs` | 语义搜索岗位 (FAISS) |
| `save_job` / `job_manage` | 保存/删除/计数岗位 |
| `application_store` | 投递记录管理 |
| `interview_tracker` | 面试漏斗追踪 |
| `stats` | 求职统计数据 |
| `memory_tools` | 记忆 CRUD (save/get/search/update/delete/cognitive_model) |
| `user_profile` | 用户档案读写 |
| `blacklist` | 公司黑名单管理 |
| `export` | 数据导出 CSV |
| `chat_history` | 对话历史 JSONL 存储 |
| `execution_trace` | 执行轨迹记录 |

#### Getjob Tools (外部爬虫服务交互)
| Tool | 功能 |
|------|------|
| `platform_status` | 查询平台任务状态 |
| `platform_control` | 启动/停止爬取任务 |
| `platform_config` | 读取/更新平台配置 |
| `platform_sync` | 同步远端岗位到本地 DB |
| `platform_stats` | 平台统计数据 |
| `platform_deliver` | 执行投递打招呼 |
| `fetch_detail` | 爬取单个岗位详情 JD |
| `service_manager` | getjob 服务管理 |

#### Browser Tools
| Tool | 功能 |
|------|------|
| `web_fetch` | 抓取网页内容 |
| `web_search` | 网页搜索 |

#### AI Tools
| Tool | 功能 |
|------|------|
| `get_skill_content` | 按需加载 Skill 完整内容 |

### 5.3 Skills 系统 (`boss-agent/skills/`)

Skills 是场景参考规范，为 AI 提供特定场景下的上下文和执行逻辑参考。

| Skill | 场景 |
|-------|------|
| `简历生成/` | 简历生成与优化 |
| `猎聘岗位采集与投递/` | 猎聘平台岗位爬取和投递流程 |
| `面试准备/` | 面试准备建议 |
| `模拟打招呼/` | 生成个性化打招呼语 |

每个 Skill 是一个文件夹，包含 `SKILL.md`（YAML frontmatter + Markdown 正文）。System Prompt 只注入摘要，完整内容通过 `get_skill_content` 按需加载。

### 5.4 Services 层 (`boss-agent/services/`)

| 文件 | 职责 |
|------|------|
| `task_monitor.py` | 后台任务监控 + 通知队列，轮询爬取任务状态，完成时通知 Agent |
| `task_state.py` | 全局任务状态存储，供前端任务面板读取 |

### 5.5 RAG 层 (`boss-agent/rag/`)

| 文件 | 职责 |
|------|------|
| `job_index.py` | 基于 FAISS 的岗位向量索引，支持语义检索 |
| `embedding.py` | Embedding 函数封装 |

### 5.6 数据持久层

| 存储 | 路径 | 用途 |
|------|------|------|
| SQLite | `db/boss_agent.db` | 岗位、简历、投递、面试、匹配分析、用户配置 |
| Markdown 文件 | `data/记忆画像/*.md` | 用户记忆画像（10 个分类） |
| JSONL 文件 | `data/conversations/*.jsonl` | 对话历史 |
| FAISS 索引 | `data/job_index/` | 岗位向量索引 |
| JSON 日志 | `data/traces/` | 执行轨迹 |
| 文本日志 | `data/logs/` | 对话日志 |

---

## 六、数据库 Schema 概览

```
resumes (简历/人物画像)
  ├── 基本信息: name, phone, email, city, birth_year
  ├── 教育: education_level, school, education_major
  ├── 职业: years_of_experience, current_company, current_role
  ├── 结构化: tech_stack, skills_flat, work_experience, projects, highlights (JSON)
  └── raw_text, structured_resume

job_preferences (求职意向)
  ├── target_cities, target_roles, target_industries (JSON)
  ├── salary_min/max, experience_match, education_min
  └── deal_breakers, priorities (JSON)

jobs (岗位库)
  ├── 基本: title, company, salary_min/max, city, platform
  ├── 要求: experience, education, skills, responsibilities (JSON)
  ├── 公司: company_size, company_industry, company_stage
  ├── JD: raw_jd, structured_jd
  └── AI: match_score, match_detail

match_results (匹配分析)
  ├── 维度评分: overall/skill/experience/salary/location/education_score
  └── 差距: missing_skills, matching_skills, skill_gaps

applications (投递记录)
  └── job_id, resume_id, greeting, status

interview_tracking (面试追踪)
  └── application_id, stage, interview_time

user_preferences (KV 配置)
blacklist (公司黑名单)
knowledge_docs (知识库索引)
```

---

## 七、外部服务交互

### 7.1 getjob 服务 (Java/Spring Boot)

```
OfferBot (Python)  ←HTTP→  getjob 服务 (Java, port 8888)
                              │
                              ├── /api/{platform}/start — 启动爬取
                              ├── /api/{platform}/stop — 停止爬取
                              ├── /api/{platform}/status — 查询状态
                              ├── /api/{platform}/config — 配置管理
                              ├── /api/{platform}/list — 岗位列表
                              ├── /api/{platform}/job-detail — 爬取 JD
                              ├── /api/{platform}/batch-detail — 批量爬取
                              ├── /api/{platform}/stats — 统计
                              ├── /api/{platform}/deliver — 投递
                              └── /api/health — 健康检查
```

### 7.2 LLM API

通过 `LLMClient` 统一调用，支持多厂商切换（base_url 区分）：
- DashScope (通义千问 Qwen3 系列) — 默认
- OpenAI (GPT-4o)
- Google Gemini
- DeepSeek

### 7.3 后台任务监控流程

```
用户: "帮我爬取猎聘岗位"
  │
  ├── Agent 调用 platform_start_task → getjob 启动爬取
  ├── TaskMonitor.start_polling() → 后台轮询任务状态
  │     │
  │     ├── 每 3s 调用 getjob /status
  │     ├── 进度回调更新 UI
  │     └── 任务完成时:
  │           ├── 执行 on_complete (自动同步数据)
  │           ├── 入队 TaskNotification
  │           └── 如果 agent 不忙 → 直接推送 UI
  │
  └── Executor 每轮工具执行后 drain 通知队列
        └── 通知注入到消息历史 → LLM 感知任务完成
```

---

## 八、记忆系统

### 8.1 记忆分类 (10 个)

| 分类 | 中文名 |
|------|--------|
| personal_thoughts | 个人想法 |
| job_sprint_goals | 求职冲刺目标 |
| language_style | 语言风格 |
| personality_traits | 性格特征 |
| hobbies_interests | 兴趣爱好 |
| career_planning | 职业规划 |
| personal_needs | 个人需求 |
| key_points | 要点信息 |
| communication_preferences | 沟通偏好 |
| values_beliefs | 价值观 |

### 8.2 记忆生命周期

```
对话中用户透露信息
  → 对话结束 / 新建对话时触发
  → MemoryExtractor (独立 LLM 调用)
  → 分析对话 + 对比已有记忆
  → save_memory / update_memory / delete_memory
  → 写入 data/记忆画像/{分类}.md
  → 下次对话启动时加载到 System Prompt
```

---

## 九、配置管理

配置来源优先级: 数据库 (user_preferences) > 环境变量 > 默认值

关键配置项:
- `DASHSCOPE_API_KEY` — LLM API Key
- `API_BASE_URL` — LLM API 地址
- `DASHSCOPE_LLM_MODEL` — 模型名 (默认 qwen3.6-plus)
- `DB_PATH` — SQLite 数据库路径
- `MEMORY_DIR` — 记忆文件目录

---

## 十、技术栈

| 层 | 技术 |
|----|------|
| 前端 | Chainlit (对话 UI) + FastAPI (管理页面) + Jinja2 模板 |
| Agent 引擎 | 自研 ReAct Loop + OpenAI Function Calling |
| LLM | OpenAI 兼容 API (DashScope/OpenAI/Gemini/DeepSeek) |
| 数据库 | SQLite (aiosqlite, WAL 模式) |
| 向量检索 | FAISS + DashScope Embedding |
| 爬虫服务 | Java Spring Boot (getjob, 独立进程) |
| HTTP 客户端 | httpx (异步) |
| 文件解析 | pdfplumber (PDF), python-docx (DOCX) |
| 开发环境 | tmux + iTerm2 + uvicorn --reload |
