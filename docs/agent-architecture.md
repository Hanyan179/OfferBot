# OfferBot Agent 架构设计

> 先定义架构需要什么能力接口，再逐个实现。实现只是填空。
> 当前核心问题：方法大部分已实现，缺的是路由层 — "谁在什么时候被调用"的调度逻辑。

## 当前进度总结

**已完成的**：
- ReAct Loop 执行引擎（executor.py）✅
- LLM 客户端（llm_client.py，支持多厂商）✅
- 31 个 Tool 的 execute() 实现 ✅
- 数据库 schema + CRUD ✅
- 记忆系统（子 Agent 提取 + 文件存储）✅
- Skills 加载器（skill_loader.py）✅
- LightRAG 知识图谱集成 ✅
- Getjob 服务交互（GetjobClient）✅
- Web 层（FastAPI + Chainlit）✅
- 测试接口（/api/test/chat）✅

**未完成 / 需要改的**：
- ❌ 路由层：31 个工具全塞给 LLM，没有分组和按需注入
- ❌ System Prompt 臃肿：所有场景策略堆在一起
- ❌ 数据状态感知：新用户和老用户看到一样的工具集
- ❌ 子 Agent 工具隔离：记忆写入工具暴露给主 Agent
- ❌ 部分 Tool 未经真实环境测试（需逐个验证）
- ❌ 项目文档（docs/）需要跟代码一一对应
- ❌ 评测平台（Langfuse 已部署，未接入测试集）

## 核心思路

Agent 就是一个调度器。它需要的不是 31 个工具，而是几个清晰的能力接口。每个接口背后怎么实现，Agent 不关心。

```
Agent 看到的世界：

  "我能做什么？"
    → 查岗位、推荐岗位、分析匹配、了解用户、采集数据、投递岗位、查进度

  "每件事怎么做？"
    → 调对应的能力接口，拿到结果，回复用户
```

## Agent 能力接口定义

Agent 需要的能力，按场景倒推：

### 1. 用户能力

| 接口 | 说明 | 对应场景 | 实现文件 | 状态 |
|------|------|---------|---------|------|
| `get_user_profile()` | 获取用户结构化画像 | 所有需要了解用户的场景 | `tools/data/user_profile.py` → GetUserProfileTool | ✅ 已实现 |
| `update_user_profile(data)` | 更新用户画像 | 子 Agent / 简历解析 | `tools/data/user_profile.py` → UpdateUserProfileTool | ✅ 已实现（应移到子Agent） |
| `get_user_cognitive_model()` | 获取记忆分类摘要 | 需要了解用户全貌时 | `tools/data/memory_tools.py` → GetUserCognitiveModelTool | ✅ 已实现 |
| `get_memory(category)` | 获取单维度记忆详情 | 需要深入了解某方面时 | `tools/data/memory_tools.py` → GetMemoryTool | ✅ 已实现 |
| `search_memory(keyword)` | 搜索记忆 | 跨分类查找信息 | `tools/data/memory_tools.py` → SearchMemoryTool | ✅ 已实现 |
| `save_memory(...)` | 保存记忆 | 子 Agent 专用 | `tools/data/memory_tools.py` → SaveMemoryTool | ✅ 已实现（应移到子Agent） |
| `update_memory(...)` | 更新记忆 | 子 Agent 专用 | `tools/data/memory_tools.py` → UpdateMemoryTool | ✅ 已实现（应移到子Agent） |
| `delete_memory(...)` | 删除记忆 | 子 Agent 专用 | `tools/data/memory_tools.py` → DeleteMemoryTool | ✅ 已实现（应移到子Agent） |

实现层：子 Agent（memory_extractor.py）负责画像构建，主 Agent 只读取。简历解析是程序性功能。

### 2. 数据查询能力

| 接口 | 说明 | 对应场景 | 实现文件 | 状态 |
|------|------|---------|---------|------|
| `query_jobs(filters)` | SQL 条件查询岗位 | S3.1 条件筛选, S3.5 精确查找 | `tools/data/query_jobs.py` → QueryJobsTool | ✅ 已实现已测试 |
| `rag_query(query, mode)` | 知识图谱语义检索 | S3.2 推荐, S3.3 相似, S3.4 知识问答, S4 匹配分析 | `tools/data/rag_query.py` → RAGQueryTool | ✅ 已实现，P0 场景已测试 |
| `get_stats()` | 统计概览 | S6 进度追踪 | `tools/data/stats.py` → GetStatsTool | ✅ 已实现 |
| `job_count()` | 岗位数量 | 状态判断 | `tools/data/job_manage.py` → JobCountTool | ✅ 已实现 |
| `get_interview_funnel()` | 面试漏斗 | S6 进度追踪 | `tools/data/interview_tracker.py` → GetInterviewFunnelTool | ✅ 已实现 |

实现层：query_jobs 走 SQL，rag_query 走 LightRAG（DashScope Embedding + 千问 LLM），get_stats 走 SQL 聚合。

### 3. 数据采集能力

| 接口 | 说明 | 对应场景 | 实现文件 | 状态 |
|------|------|---------|---------|------|
| `platform_start_task(params)` | 启动岗位爬取任务 | S2.1 搜索新岗位 | `tools/getjob/platform_control.py` → PlatformStartTaskTool | ✅ 已实现，需真实测试 |
| `platform_stop_task()` | 停止爬取 | S2.1 | `tools/getjob/platform_control.py` → PlatformStopTaskTool | ✅ 已实现，需真实测试 |
| `platform_status()` | 查询爬取状态 | S2.1 | `tools/getjob/platform_status.py` → PlatformStatusTool | ✅ 已实现 |
| `fetch_job_detail(job_ids)` | 爬取岗位详情 JD | S2.2 | `tools/getjob/fetch_detail.py` → FetchJobDetailTool | ✅ 已实现已测试 |
| `sync_jobs()` | 同步远端数据到本地 | S2.3 | `tools/getjob/platform_sync.py` → SyncJobsTool | ✅ 已实现，需真实测试 |

实现层：全部通过 GetjobClient 调用 Java 服务。fetch_detail 完成后自动 LightRAG 图谱化。

### 4. 求职行动能力

| 接口 | 说明 | 对应场景 | 实现文件 | 状态 |
|------|------|---------|---------|------|
| `platform_deliver(job_id, greeting)` | 投递岗位 + 打招呼 | S5.1 投递 | `tools/getjob/platform_deliver.py` → PlatformDeliverTool | ✅ 已实现，需真实测试 |
| `save_application(...)` | 记录投递 | S5.1 投递后记录 | `tools/data/application_store.py` → SaveApplicationTool | ✅ 已实现 |
| 打招呼语生成 | 个性化打招呼语 | S5.2 | `skills/模拟打招呼/SKILL.md` | ✅ Skill 已定义 |

实现层：deliver 通过 GetjobClient 调浏览器自动化。打招呼语生成是 Skill。

### 5. 元能力（Agent 自身管理）— 需要新建

| 接口 | 说明 | 用途 | 实现文件 | 状态 |
|------|------|------|---------|------|
| `activate_toolset(name)` | 激活场景工具集 | 当核心集不够用时，LLM 主动请求 | 待新建 | ❌ 未实现 |
| `get_data_status()` | 获取当前数据状态 | 判断有没有数据、该引导用户做什么 | 待新建 | ❌ 未实现 |

### 6. 其他已实现但需归类的能力

| 接口 | 说明 | 实现文件 | 状态 | 归属 |
|------|------|---------|------|------|
| `web_fetch(url)` | 抓取网页内容 | `tools/browser/web_fetch.py` | ✅ 已实现 | Web 场景集 |
| `web_search(query)` | 网页搜索 | `tools/browser/web_search.py` | ✅ 已实现 | Web 场景集 |
| `platform_get_config()` | 读取平台配置 | `tools/getjob/platform_config.py` | ✅ 已实现 | 管理场景集 |
| `platform_update_config()` | 更新平台配置 | `tools/getjob/platform_config.py` | ✅ 已实现 | 管理场景集 |
| `platform_stats()` | 平台统计 | `tools/getjob/platform_stats.py` | ✅ 已实现 | 管理场景集 |
| `getjob_service_manager()` | 服务管理 | `tools/getjob/service_manager.py` | ✅ 已实现 | 管理场景集 |
| `update_interview_status()` | 更新面试状态 | `tools/data/interview_tracker.py` | ✅ 已实现 | 进度追踪 |
| `save_job()` | 保存岗位 | `tools/data/job_store.py` | ✅ 已实现 | 程序性，不需要 Agent 调 |
| `delete_jobs()` | 删除岗位 | `tools/data/job_manage.py` | ✅ 已实现 | 管理场景集 |
| `add/remove_blacklist()` | 黑名单管理 | `tools/data/blacklist.py` | ✅ 已实现 | UI 操作，不需要 Agent 调 |
| `export_csv()` | 导出 CSV | `tools/data/export.py` | ✅ 已实现 | UI 操作，不需要 Agent 调 |
| `get_skill_content(name)` | 获取 Skill 内容 | `tools/ai/get_skill_content.py` | ✅ 已实现 | 路由层自动注入，不需要 Agent 主动调 |
| `list_memory_categories()` | 列出记忆分类 | `tools/data/memory_tools.py` | ✅ 已实现 | 子 Agent 用 |

---

## 架构分层

```
┌─────────────────────────────────────────────────┐
│              Agent 层（调度器）                    │
│                                                 │
│  System Prompt + 核心能力接口 + ReAct Loop       │
│  只关心"调什么接口"，不关心"怎么实现"              │
└──────────────────────┬──────────────────────────┘
                       │ 调用能力接口
                       ▼
┌─────────────────────────────────────────────────┐
│              能力接口层（抽象）                    │
│                                                 │
│  用户能力 │ 查询能力 │ 采集能力 │ 行动能力 │ 元能力 │
│                                                 │
│  每个接口 = 一个 Tool 的 execute() 方法           │
│  接口定义清晰，输入输出明确                       │
└──────────────────────┬──────────────────────────┘
                       │ 具体实现
                       ▼
┌─────────────────────────────────────────────────┐
│              实现层（可替换）                      │
│                                                 │
│  SQLite │ LightRAG │ GetjobClient │ LLM API     │
│  记忆文件 │ 子Agent │ 浏览器自动化                │
│                                                 │
│  实现可以随时替换，不影响 Agent 层                 │
│  （比如 LightRAG 换成别的 RAG，Agent 无感知）     │
└─────────────────────────────────────────────────┘
```

## 与现状的差距

### 现在的问题
1. 31 个 Tool 全部平铺注册，Agent 每次都看到全部
2. 没有能力分层，Tool 实现细节暴露给 Agent
3. 子 Agent 的工具（记忆写入）和主 Agent 的工具混在一起
4. System Prompt 塞了所有场景的策略说明，大部分时候是浪费
5. 没有数据状态感知，新用户和老用户看到一样的工具集

### 目标
1. Agent 只看到 6 个核心能力接口 + 1 个 activate_toolset
2. 场景工具按需加载，LLM 主动请求
3. 子 Agent 的工具完全隔离
4. System Prompt 精简，场景策略按需注入
5. 会话开始时感知数据状态，决定初始引导方向

### 改动范围
- `tool_registry.py` — 支持工具集分组 + 按组获取 schema
- `executor.py` — chat() 方法支持动态工具列表
- `bootstrap.py` — 注册时标记工具集归属
- `system_prompt.py` — 精简，场景策略拆成独立片段
- 新增 `activate_toolset` Tool
- 新增 `get_data_status` Tool
- 现有 Tool 代码不动

### 不改的东西
- 所有现有 Tool 的 execute() 实现
- 数据库 schema
- LLM 调用方式
- Web 层
- 外部服务交互

---

## 实施路径

| 步骤 | 内容 | 状态 |
|------|------|------|
| 1 | 场景定义（docs/scene-definition.md） | ✅ 已完成 |
| 2 | 能力接口定义 + 实现状态盘点（本文档） | ✅ 已完成 |
| 3 | **→ 路由层设计（核心集 + activate_toolset + 工具集分组）** | ❌ 当前卡点 |
| 4 | 改 ToolRegistry 支持分组 | ❌ 待实施 |
| 5 | 改 Executor 支持动态工具列表 | ❌ 待实施 |
| 6 | 实现 activate_toolset + get_data_status | ❌ 待实施 |
| 7 | 精简 System Prompt | ❌ 待实施 |
| 8 | 逐个 Tool 真实环境测试 | ❌ 待实施 |
| 9 | 接入 Langfuse 评测平台 | ❌ Langfuse 已部署(localhost:3000)，未接入 |
| 10 | 项目文档完善（docs/ 跟代码一一对应） | 🔄 进行中 |

**当前核心任务：步骤 3 — 路由层设计。这是唯一缺失的架构层。方法都有了，缺的是调度。**
