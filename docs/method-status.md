# OfferBot 方法状态清单

> 按场景列出所有需要的方法、实现文件、当前状态、是否经过真实测试。
> 用于任务分配和进度跟踪。

## 状态说明

- ✅ 已实现已测试 — 代码写好了，真实环境跑过，确认可用
- 🔧 已实现未测试 — 代码写好了，但没在真实环境验证过
- ❌ 未实现 — 还没写
- 🚫 废弃 — 不再需要或将移到子 Agent

---

## S1：用户画像（子 Agent 管理）

| 方法 | 实现文件 | 状态 | 真实测试 | 备注 |
|------|---------|------|---------|------|
| `get_user_profile()` | `tools/data/user_profile.py` → GetUserProfileTool | ✅ | ✅ 对话中频繁调用 | 核心集，始终可用 |
| `update_user_profile(data)` | `tools/data/user_profile.py` → UpdateUserProfileTool | ✅ | ✅ | 移到 sub_agent/deprecated，主 Agent 不直接调 |
| `get_user_cognitive_model()` | `tools/data/memory_tools.py` → GetUserCognitiveModelTool | ✅ | ✅ | 核心集，只读 |
| `get_memory(category)` | `tools/data/memory_tools.py` → GetMemoryTool | ✅ | ✅ | 核心集，只读 |
| `search_memory(keyword)` | `tools/data/memory_tools.py` → SearchMemoryTool | ✅ | ✅ 2026-04-07 真实测试通过 | 核心集，只读 |
| `save_memory(...)` | `tools/data/memory_tools.py` → SaveMemoryTool | ✅ | ✅ 子 Agent 调用 | 移到 sub_agent |
| `update_memory(...)` | `tools/data/memory_tools.py` → UpdateMemoryTool | ✅ | ✅ 子 Agent 调用 | 移到 sub_agent |
| `delete_memory(...)` | `tools/data/memory_tools.py` → DeleteMemoryTool | ✅ | ✅ 单元测试通过 | 移到 sub_agent |
| `list_memory_categories()` | `tools/data/memory_tools.py` → ListMemoryCategoryTool | ✅ | ✅ 2026-04-07 真实测试通过 | 移到 sub_agent |
| 简历解析（PDF/DOCX） | `web/chat.py` 中 `_parse_attachment()` | ✅ | ✅ | 程序性功能，不是 Tool |
| 记忆提取子 Agent | `agent/memory_extractor.py` → MemoryExtractor | ✅ | ✅ | 对话结束后自动运行 |

---

## S2：数据采集

| 方法 | 实现文件 | 状态 | 真实测试 | 备注 |
|------|---------|------|---------|------|
| `platform_start_task(params)` | `tools/getjob/platform_control.py` → PlatformStartTaskTool | ✅ | ✅ 2026-04-07 真实测试通过 | crawl 集 |
| `platform_stop_task()` | `tools/getjob/platform_control.py` → PlatformStopTaskTool | ✅ | ✅ 2026-04-07 真实测试通过 | crawl 集 |
| `platform_status()` | `tools/getjob/platform_status.py` → PlatformStatusTool | ✅ | ✅ 2026-04-07 真实测试通过 | crawl 集 |
| `fetch_job_detail(job_ids)` | `tools/getjob/fetch_detail.py` → FetchJobDetailTool | ✅ | ✅ 真实爬取过 | crawl 集 |
| `sync_jobs()` | `tools/getjob/platform_sync.py` → SyncJobsTool | ✅ | ✅ 2026-04-07 真实测试通过（508新增/492更新） | crawl 集 |
| LightRAG 自动图谱化 | `tools/getjob/fetch_detail.py` 中 `job_rag.insert_jobs_batch()` | ✅ | ✅ | fetch_detail 完成后自动触发 |
| `TaskMonitor 后台轮询` | `services/task_monitor.py` | ✅ | ✅ platform_start_task 测试中联动验证 | 爬取任务状态轮询 + 完成通知 |
| GetjobClient HTTP 客户端 | `services/getjob_client.py` | ✅ | ✅ 部分接口 | 封装所有 Getjob REST API |

**真实测试依赖**：需要 Getjob Java 服务运行在 localhost:8888

---

## S3：知识检索与岗位发现

| 方法 | 实现文件 | 状态 | 真实测试 | 备注 |
|------|---------|------|---------|------|
| `query_jobs(filters)` | `tools/data/query_jobs.py` → QueryJobsTool | ✅ | ✅ P0 场景测试通过 | 核心集 |
| `rag_query(query, mode="answer")` | `tools/data/rag_query.py` → RAGQueryTool | ✅ | ✅ P0 场景测试通过 | 核心集 |
| `rag_query(query, mode="search")` | `tools/data/rag_query.py` → RAGQueryTool | ✅ | ✅ P0 场景测试通过 | 核心集 |
| JobRAG.query_for_agent() | `rag/job_rag.py` | ✅ | ✅ | LightRAG hybrid 检索 |
| JobRAG.query_entities() | `rag/job_rag.py` | ✅ | ✅ 2026-04-07 rag_query(mode=search) 联动验证 | 从图谱提取岗位 ID → 查 DB |
| JobRAG.insert_job/batch() | `rag/job_rag.py` | ✅ | ✅ | 岗位数据图谱化 |

**真实测试依赖**：需要本地有岗位数据 + LightRAG 已初始化

---

## S4：匹配分析

| 方法 | 实现文件 | 状态 | 真实测试 | 备注 |
|------|---------|------|---------|------|
| 匹配度分析 | 组合调用：`get_user_profile` + `rag_query(mode="answer")` | ✅ | ✅ 2026-04-07 真实测试通过（job 3691） | 依赖 LLM 路由正确 |
| 技能差距分析 | 组合调用：`get_user_profile` + `rag_query(mode="answer")` | ✅ | ✅ 2026-04-07 同上联动验证 | 依赖 LLM 路由正确 |
| 批量对比 | 组合调用：`get_user_profile` + 多次 `rag_query` | ✅ | ✅ 2026-04-07 真实测试通过（3岗位对比） | 依赖 LLM 路由正确 |

**备注**：匹配分析不是独立方法，是 LLM 组合调用核心工具完成的。路由层做好后准确率会提升。

---

## S5：求职行动

| 方法 | 实现文件 | 状态 | 真实测试 | 备注 |
|------|---------|------|---------|------|
| `platform_deliver(job_id, greeting)` | `tools/getjob/platform_deliver.py` → PlatformDeliverTool | ✅ | ❌ GetjobClient 缺少 deliver 方法 | deliver 集 |
| `save_application(...)` | `tools/data/application_store.py` → SaveApplicationTool | ✅ | ✅ 2026-04-07 真实测试通过（job_id=4914） | deliver 集 |
| 打招呼语生成 Skill | `skills/模拟打招呼/SKILL.md` | ✅ | ✅ 2026-04-07 真实测试通过 | Skill 定义已有 |

**真实测试依赖**：需要 Getjob 服务 + 浏览器自动化环境

---

## S6：进度追踪

| 方法 | 实现文件 | 状态 | 真实测试 | 备注 |
|------|---------|------|---------|------|
| `get_stats()` | `tools/data/stats.py` → GetStatsTool | ✅ | ✅ | 核心集 |
| `job_count()` | `tools/data/job_manage.py` → JobCountTool | ✅ | ✅ | 核心集 |
| `get_interview_funnel()` | `tools/data/interview_tracker.py` → GetInterviewFunnelTool | ✅ | ✅ 2026-04-07 真实测试通过 | 核心集 |
| `update_interview_status()` | `tools/data/interview_tracker.py` → UpdateInterviewStatusTool | ✅ | ✅ 单元测试 33/33 通过 | deprecated（程序性操作） |

---

## 元能力（路由层，待实现）

| 方法 | 实现文件 | 状态 | 备注 |
|------|---------|------|------|
| `activate_toolset(name)` | `tools/meta/activate_toolset.py` | ❌ 未实现 | toolset-routing spec 任务 2.1 |
| `get_data_status()` | `tools/meta/get_data_status.py` | ❌ 未实现 | toolset-routing spec 任务 2.2 |
| ToolRegistry.get_schemas_for_toolsets() | `agent/tool_registry.py` | ❌ 未实现 | toolset-routing spec 任务 1 |
| Executor 动态工具列表 | `agent/executor.py` | ❌ 未实现 | toolset-routing spec 任务 4 |

---

## 基础设施

| 组件 | 实现文件 | 状态 | 真实测试 | 备注 |
|------|---------|------|---------|------|
| ReAct Loop 执行引擎 | `agent/executor.py` | ✅ | ✅ | 核心引擎 |
| LLM 客户端 | `agent/llm_client.py` | ✅ | ✅ | 支持 DashScope/OpenAI/Gemini |
| ToolRegistry | `agent/tool_registry.py` | ✅ | ✅ | 需扩展 toolset 分组 |
| System Prompt | `agent/system_prompt.py` | ✅ | ✅ | 需精简 |
| SkillLoader | `agent/skill_loader.py` | ✅ | ✅ | Skills 加载器 |
| Database (SQLite) | `db/database.py` | ✅ | ✅ | WAL 模式 |
| Web 层 (FastAPI + Chainlit) | `web/app.py` + `web/chat.py` | ✅ | ✅ | |
| 测试接口 | `web/app.py` → `api_test_chat` | ✅ | ✅ | 需适配 toolset 过滤 |
| Langfuse 评测平台 | `~/langfuse/docker-compose.yml` | ✅ 已部署 | 🔧 未接入测试集 | localhost:3000 |

---

## 废弃/不需要 Agent 调用的方法

| 方法 | 实现文件 | 原因 |
|------|---------|------|
| `save_job()` | `tools/data/job_store.py` | 程序性操作，sync_jobs 自动处理 |
| `add_to_blacklist()` | `tools/data/blacklist.py` | UI 操作 |
| `remove_from_blacklist()` | `tools/data/blacklist.py` | UI 操作 |
| `export_csv()` | `tools/data/export.py` | UI 操作 |
| `get_skill_content()` | `tools/ai/get_skill_content.py` | 路由层自动注入，不需要 LLM 主动调 |
| `delete_jobs()` | `tools/data/job_manage.py` | 管理操作，放 admin 集 |

---

## 真实测试优先级

### P0 — 必须先验证（核心流程）
1. `query_jobs` ✅ 已验证
2. `rag_query` ✅ 已验证
3. `get_user_profile` ✅ 已验证
4. `get_stats` ✅ 已验证
5. `fetch_job_detail` ✅ 已验证
6. LightRAG 图谱化 ✅ 已验证

### P1 — 需要 Getjob 服务验证
7. `platform_start_task` ✅ 2026-04-07 已验证
8. `platform_stop_task` ✅ 2026-04-07 已验证
9. `platform_status` ✅ 2026-04-07 已验证
10. `sync_jobs` ✅ 2026-04-07 已验证
11. `platform_deliver` ❌ GetjobClient 缺少 deliver 方法，需实现

### P2 — 路由层完成后验证
12. `activate_toolset` ❌ 待实现
13. `get_data_status` ❌ 待实现
14. 端到端场景路由测试 ❌ 待实现

### P3 — 评测平台接入
15. Langfuse 测试集接入 🔧 已部署未接入
