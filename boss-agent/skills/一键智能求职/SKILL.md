---
name: 一键智能求职
description: 基于用户画像，自动完成环境检查→条件构建→爬取岗位→数据过滤→分批量化匹配→TopN筛选的全流程编排
when_to_use: 当用户说"一键求职"、"帮我自动找工作"、"全自动搜索匹配"、"autopilot"、"帮我从头到尾跑一遍"时
memory_categories: [job_sprint_goals, career_planning, key_points]
allowed-tools: [get_user_profile, get_memory, getjob_service_manage, platform_status, platform_update_config, platform_start_task, platform_stop_task, sync_jobs, platform_stats, query_jobs, fetch_job_detail, rag_query, search_jobs_semantic, get_stats]
---

## 场景描述

用户希望一键走通"画像→爬取→过滤→匹配→筛选"全流程。AI 作为编排者，每一步都先用工具检查系统实际状态，根据检查结果决定下一步动作。不假设任何前置条件，缺什么补什么，需要用户授权的地方必须停下来等确认。

## 核心原则

1. **先检查再行动**：每一步都先调工具查实际状态，不凭记忆假设
2. **缺什么补什么**：没简历就引导上传，没登录就引导扫码，没数据就触发爬取
3. **用户授权门控**：爬取和投递必须通过 ActionCard 让用户确认
4. **爬取与分析解耦**：爬取完成后先问用户要不要做匹配分析，分析消耗 token
5. **程序化过滤先行**：AI 匹配之前，先用确定性规则过滤掉无效/不合格数据
6. **量化指标体系**：匹配度由 7 个维度加权计算，每个维度 0-100 分

---

## 涉及工具清单（15 个）

本场景涉及 14 个工具，按用途分为 4 组。`allowed-tools` 已全部列出。

### 画像 & 记忆（2 个）

| 工具名 | 用途 | 关键参数 | 使用步骤 |
|--------|------|---------|---------|
| `get_user_profile` | 获取简历+求职意向 | 无参数 | Step 1 |
| `get_memory` | 获取记忆分类内容 | `category`: 如 "job_sprint_goals" | Step 1 |

### getjob 服务控制（8 个）

| 工具名 | 用途 | 关键参数 | 使用步骤 |
|--------|------|---------|---------|
| `getjob_service_manage` | 检查/启动/停止 getjob 服务 | `action`: "check"/"start"/"stop" | Step 2 |
| `platform_status` | 查猎聘任务状态+登录状态 | `platform`: "liepin" | Step 2 |
| `platform_update_config` | 更新搜索配置（关键词/城市/薪资） | `platform`, `config`: {keywords, city, salaryCode, scrapeOnly} | Step 3 |
| `platform_start_task` | 启动爬取/投递任务 | `platform`: "liepin" | Step 3 |
| `platform_stop_task` | 停止正在运行的任务 | `platform`: "liepin" | 中断时 |
| `sync_jobs` | 从 getjob 同步岗位到本地 DB | `platform`: "liepin" | Step 4 |
| `platform_stats` | 获取爬取/投递统计 | `platform`: "liepin" | Step 4 进度查询 |
| `fetch_job_detail` | 爬取单个岗位的完整 JD | `job_id` 或 `job_ids` | Step 5（补 JD） |

### 数据查询 & 检索（3 个）

| 工具名 | 用途 | 关键参数 | 使用步骤 |
|--------|------|---------|---------|
| `query_jobs` | SQL 条件筛选本地岗位 | `keyword`, `city`, `salary_min`, `jd_status`, `limit` | Step 3/4/7 |
| `rag_query` | 知识图谱+向量混合检索 | `query`, `mode`: "answer"/"search" | Step 6 |
| `search_jobs_semantic` | 纯向量语义搜索岗位 | `query`, `top_k` | Step 6 |

### 统计（1 个）

| 工具名 | 用途 | 关键参数 | 使用步骤 |
|--------|------|---------|---------|
| `get_stats` | 获取投递统计 | 无参数 | Step 7 后续 |

---

## 全流程编排（7 步）

```
Step 1: 检查画像 → Step 2: 检查服务/登录 → Step 3: 配置+爬取
    → Step 4: 同步+程序化过滤 → Step 5: 询问用户意图
    → Step 6: 分批量化匹配 → Step 7: TopN 结果展示
```

---

### Step 1：检查用户画像

**必须首先执行。**

调用 `get_user_profile()`

#### 情况 A：有简历（has_profile=true）

提取关键字段并暂存：
- `name`, `city`, `current_role`, `years_of_experience`
- `skills` — 技能列表
- `highlights` — 核心亮点
- `job_preferences.target_cities` — 目标城市
- `job_preferences.target_roles` — 目标岗位
- `job_preferences.salary_min` / `salary_max` — 期望薪资
- `job_preferences.deal_breakers` — 绝对不接受的条件
- `job_preferences.priorities` — 求职优先级

补充调用 `get_memory(category="job_sprint_goals")` 获取近期求职目标。

汇报：
> ✅ 画像就绪：{name}，{city}，目标 {target_roles}，期望 {salary_min}-{salary_max}K

继续 Step 2。

#### 情况 B：无简历（has_profile=false）

**停止流程**：
> ❌ 还没有简历数据，无法构建搜索条件。
> 请先到「📄 简历」页面上传简历，或者在对话中告诉我你的背景。

**不继续。**

#### 情况 C：有简历但缺求职意向

比如有 name 但没有 target_roles 或 salary_min：
> ⚠️ 画像有了，但缺少求职意向。你想找什么方向？期望薪资？目标城市？

等用户补充后继续（不需要重新触发）。

---

### Step 2：检查 getjob 服务 & 猎聘登录

#### 2a. 检查 getjob 服务

调用 `getjob_service_manage(action="check")`

- **已运行** → 继续 2b
- **未运行** → 调用 `getjob_service_manage(action="start")`
  - 成功 → 继续 2b
  - 失败 → 告诉用户手动启动 `cd reference-crawler && ./gradlew bootRun`，等反馈

#### 2b. 检查猎聘登录

调用 `platform_status(platform="liepin")`

- **已登录** → 继续 Step 3
- **未登录** → "请在浏览器中扫码登录猎聘，完成后告诉我"，**等用户确认**
- **任务正在运行** → "有任务在跑，要等还是停？" 等用户选择

---

### Step 3：配置搜索条件 & 启动爬取

#### 3a. 先查本地数据

调用 `query_jobs(keyword="{target_roles[0]}", city="{city}", salary_min={salary_min})`

- **≥30 条匹配** → 问用户："本地已有 {count} 条匹配岗位，要直接分析还是先爬新数据？"
  - 用户选"直接分析" → 跳到 Step 4（跳过爬取）
  - 用户选"爬新数据" → 继续爬取
- **<30 条** → 继续爬取

#### 3b. 构建搜索条件

- **keywords**：从 target_roles 取前 3 个（要具体，如"AI Agent 工程师"而非"工程师"）
- **city**：target_cities[0]，没有则用 city
- **salaryCode**：从 salary_min/max 转换（见映射表）
- **scrapeOnly**：始终 true

用户在对话中明确说的条件 **优先级最高**。

#### 3c. 通过 ActionCard 确认

构造 `start_task` ActionCard 让用户确认搜索参数。用户可在卡片上修改关键词/城市/薪资。

> 🔍 根据你的画像构建了搜索条件，请确认后开始爬取 ↑

**等用户在 ActionCard 上确认。** 确认后系统自动执行 `platform_update_config` + `platform_start_task`，TaskPanel 显示进度。

---

### Step 4：同步数据 & 程序化过滤

爬取完成后（TaskMonitor 自动通知），执行数据同步和过滤。

#### 4a. 同步数据

`sync_jobs(platform="liepin")` — TaskMonitor 完成回调已自动执行。

确认同步结果：
> ✅ 同步完成：新增 {inserted} 条，更新 {updated} 条

#### 4b. 程序化过滤（确定性规则，不消耗 token）

同步后的数据需要过滤，确保质量。用 `query_jobs` 的条件筛选能力做程序化过滤：

**过滤规则（按优先级）：**

| 规则 | 检查方式 | 处理 |
|------|---------|------|
| 无效数据 | title 为空或 url 为空 | 排除 |
| 黑名单公司 | company 在 blacklist 表中 | 排除 |
| 城市不匹配 | city 不在 target_cities 中 | 排除（除非用户说"不限城市"） |
| 薪资不达标 | salary_max < salary_min（用户期望） | 排除 |
| 学历不匹配 | education 要求高于用户学历 | 标记但不排除（可能有弹性） |
| deal_breakers | JD 中包含 deal_breaker 关键词 | 排除 |

具体操作：
```
# 1. 查所有同步的岗位
query_jobs(city="{city}", salary_min={user_salary_min}, limit=200)

# 2. 结果中 AI 检查 deal_breakers（如果有 JD 的话）
# 对于没有 JD 的岗位，只能基于标题/公司做粗筛
```

过滤后汇报：
> 📊 过滤结果：{total} 条 → 过滤后 {filtered} 条有效候选
> - 排除 {n1} 条（城市不匹配）
> - 排除 {n2} 条（薪资不达标）
> - 排除 {n3} 条（黑名单公司）

---

### Step 5：询问用户意图（关键决策点）

**爬取和分析是解耦的。** 分析消耗 token，不是每次爬取都需要。

过滤完成后，问用户：

> 📋 当前有 {filtered} 条有效候选岗位。你想：
>
> 1️⃣ **只看列表** — 我把岗位列表展示给你，你自己挑感兴趣的
> 2️⃣ **AI 匹配分析** — 我逐批分析匹配度，帮你找出 Top 10（消耗约 {estimated_tokens} token）
> 3️⃣ **先补 JD 再分析** — 先爬取岗位详情（JD），再做更精准的匹配分析

#### 用户选 1：只看列表

调用 `query_jobs(...)` 展示 JobList，流程结束。用户后续可以单独说"分析第X个"。

#### 用户选 2：直接 AI 匹配

继续 Step 6。

#### 用户选 3：先补 JD 再分析

检查 JD 覆盖率 `query_jobs(jd_status="stats")`：
- 构造 `fetch_detail` ActionCard，选中缺 JD 的岗位（最多 30 条）
- 用户确认后爬取详情
- 爬取完成后继续 Step 6

---

### Step 6：分批量化匹配

**这是核心步骤。** 匹配度不是模糊的"AI 觉得合适"，而是 7 个维度的量化评分。

#### 6a. 匹配度量化指标体系

每个岗位的匹配度由以下 7 个维度加权计算：

| 维度 | 权重 | 计算方式 | 数据来源 |
|------|------|---------|---------|
| **技能匹配** skill_score | 30% | 用户 skills ∩ 岗位 skills / 岗位 skills_must | 简历 skills_flat + JD skills |
| **经验匹配** experience_score | 15% | 用户 years_of_experience vs 岗位 experience_min~max | 简历 + jobs 表 |
| **薪资匹配** salary_match | 15% | 用户期望区间 vs 岗位薪资区间的重叠度 | job_preferences + jobs 表 |
| **城市匹配** location_match | 10% | 是否在 target_cities 中 | job_preferences + jobs 表 |
| **学历匹配** education_match | 10% | 用户学历 vs 岗位要求 | 简历 + jobs 表 |
| **职责匹配** responsibility_score | 10% | 用户经历/项目 vs 岗位职责的语义相关度 | 简历 + JD responsibilities |
| **综合适配** embedding_similarity | 10% | 简历整体 vs JD 整体的向量相似度 | RAG 向量检索（如果可用） |

**综合分 = Σ(维度分 × 权重)**

#### 6b. 程序化可算维度（不消耗 token）

以下维度可以程序化计算，不需要 LLM：

**薪资匹配 salary_match**：
```
用户期望: [salary_min, salary_max]
岗位薪资: [job_salary_min, job_salary_max]

overlap = min(user_max, job_max) - max(user_min, job_min)
range = max(user_max, job_max) - min(user_min, job_min)
salary_match = max(0, overlap / range * 100)

特殊情况：
- 岗位薪资"面议" → salary_match = 50（中性）
- 岗位薪资完全覆盖用户期望 → salary_match = 100
- 完全不重叠 → salary_match = 0
```

**城市匹配 location_match**：
```
岗位城市 in target_cities → 100
岗位城市不在 target_cities 但在同省 → 50
完全不匹配 → 0
```

**学历匹配 education_match**：
```
学历等级映射: 大专=1, 本科=2, 硕士=3, 博士=4
用户学历 >= 岗位要求 → 100
用户学历 = 岗位要求 - 1 → 60（差一级，可能有弹性）
用户学历 < 岗位要求 - 1 → 20
岗位无学历要求 → 100
```

**经验匹配 experience_score**：
```
用户年限在岗位要求范围内 → 100
用户年限 > 岗位上限（资历过高） → 70
用户年限 < 岗位下限 1 年以内 → 60
用户年限 < 岗位下限 2 年以上 → 30
岗位无经验要求 → 100
```

#### 6c. LLM 评估维度（消耗 token）

以下维度需要 LLM 分析：

**技能匹配 skill_score**：
- 如果岗位有 JD（raw_jd 非空）：LLM 对比用户 skills 和 JD 中的技能要求
- 如果岗位无 JD：只能基于标题关键词粗略匹配，分数上限 60

**职责匹配 responsibility_score**：
- 需要 JD 中的职责描述
- 无 JD 时此维度 = 50（中性默认值）

**向量相似度 embedding_similarity**：
- 如果 RAG 索引可用：`search_jobs_semantic` 返回的 relevance_score
- RAG 不可用时此维度 = 50（中性默认值）

#### 6d. 分批执行策略

将候选岗位按每批 10-15 条分组。对每批：

1. **先算程序化维度**（salary_match, location_match, education_match, experience_score）
2. **再调 LLM 算剩余维度**（skill_score, responsibility_score）
3. **合并计算综合分**

LLM prompt 模板：
```
你是求职匹配分析专家。请对以下岗位评估技能匹配度和职责匹配度。

## 用户画像
- 技能: {skills}
- 工作经历摘要: {work_experience_summary}
- 项目经验摘要: {projects_summary}
- 核心亮点: {highlights}

## 候选岗位（本批 {n} 条）
[{id}] {title} | {company} | JD摘要: {jd_snippet_300chars}
...

## 输出要求
对每个岗位输出 JSON（不要其他内容）：
[{"id": 岗位ID, "skill_score": 0-100, "responsibility_score": 0-100, "missing_skills": ["缺失技能"], "matching_skills": ["匹配技能"], "reason": "一句话理由"}]
```

汇报进度：
> 🔄 匹配分析中... 第 {n}/{total} 批

#### 6e. 汇总

所有批次完成后：
- 合并 7 个维度分数，按权重计算综合分
- 按综合分降序排列
- 取 Top 10
- 将结果写入 `match_results` 表和 `jobs.match_score` 字段

---

### Step 7：展示结果 & 后续引导

#### 7a. 展示 Top N

通过 `query_jobs` 查询 Top 10 完整信息，触发 JobList UI 渲染。

文字汇报（包含量化指标）：
> 🏆 **匹配分析完成！** 从 {total} 条候选中筛选出 Top 10：
>
> 1. **{title}** — {company} · {city} · {salary}
>    综合 **{overall}分** | 技能 {skill}分 | 薪资 {salary_m}分 | 经验 {exp}分
>    {reason}
> 2. ...

#### 7b. 后续引导

> 接下来你可以：
> - "分析第X个" — 查看详细匹配报告
> - "帮我定制简历" — 针对某个岗位优化简历
> - "投递前3个" — 对选中岗位投递打招呼
> - "再爬一批" — 用不同条件继续搜索

---

## 薪资编码映射表

| 用户期望（K/月） | salaryCode |
|-----------------|-----------|
| 5-10K           | 5$10      |
| 10-15K          | 10$15     |
| 15-20K          | 15$20     |
| 20-30K          | 20$30     |
| 25-40K          | 25$40     |
| 30-50K          | 30$50     |
| 40-60K          | 40$60     |
| 50-80K          | 50$80     |
| 60K+            | 60$100    |

---

## UI 组件使用指南

### ActionCard（确认卡片）

Tool 返回 `action=confirm_required` 格式时自动渲染。可用 card_type：
- `start_task` — 启动爬取（用户可修改参数）
- `fetch_detail` — 批量获取 JD（用户可选择岗位）
- `deliver` — 投递打招呼（用户可选择岗位）

### JobList（岗位列表）

`query_jobs` 返回的 `for_ui` 自动渲染。用户通过序号引用岗位。

### TaskPanel（任务面板）

爬取启动后右侧面板自动显示进度，系统自动处理。

---

## 错误处理总表

| 步骤 | 错误 | 处理 |
|------|------|------|
| Step 1 | 无简历 | 停止，引导上传 |
| Step 1 | 画像不完整 | 询问缺失信息 |
| Step 2 | getjob 不可达 | 尝试自动启动，失败引导手动 |
| Step 2 | 未登录 | 引导扫码，等确认 |
| Step 2 | 已有任务在跑 | 问等还是停 |
| Step 3 | 配置/启动失败 | 告诉用户错误原因 |
| Step 4 | 同步后 0 条 | 建议放宽搜索条件 |
| Step 4 | 过滤后 0 条 | 建议放宽过滤条件或调整 deal_breakers |
| Step 6 | RAG 不可用 | embedding_similarity 用默认值 50 |
| Step 6 | LLM 调用失败 | 跳过该批继续，最后汇报 |
| Step 6 | 无 JD 岗位 | skill_score 上限 60，responsibility_score 默认 50 |
| Step 7 | 结果 <3 条 | 建议放宽条件重新爬取 |

---

## 中断与恢复

- 用户说"停"/"算了" → 立即停止，爬取中调用 `platform_stop_task`
- 用户说"继续" → 重新检查状态确定当前进度，从中断处恢复
- 不要在一次对话中反复启动爬取任务

---

## 注意事项

- 猎聘打招呼语由猎聘 App 设置，程序无法修改
- 每次操作前都要检查状态，不假设上一步还有效
- 用户对话中说的条件优先级高于画像数据
- 有 JD 的岗位匹配精度远高于无 JD 的，建议用户补充 JD
- 无 JD 岗位的 skill_score 上限 60，responsibility_score 默认 50
- 整个流程可能需要几分钟，告诉用户可以继续聊天
- 匹配结果写入 match_results 表，后续可做反馈闭环分析
