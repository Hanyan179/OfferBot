# 🐄 MooBot

**一头牛马（作者）为了求职，爆肝 4 天，用牛马（coding agent）开发了个牛马（求职 agent）来帮自己找工作。**

**希望可以为各位牛马提供帮助，moo～**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)

[快速开始](docs/getting-started.md) · [配置说明](docs/configuration.md) · [Tool 开发](docs/tool-development.md) · [FAQ](docs/faq.md) · [贡献指南](CONTRIBUTING.md)

---

## 为什么做这个

我自己在找 AI 方向的工作。

普通人，普通学历，普通能力。AI 时代来了，机会变多了，但欲望也跟着放大了——想做产品，想做项目，想了很多，接触了很多。但回到现实还是要找工作，而找工作的时候才发现：一个普通的我，到底能找什么？自己的定位都不清晰。

找工作的时候，最难的不是投简历，是不知道该投哪。我到底适合什么岗位？我现在的能力，市场认吗？JD 上写的那些要求，我够得上几条？越看越焦虑，越想越模糊。

但说实话，心里不是完全没方向。就像抛硬币——嘴上说随便，硬币还在空中的时候，其实已经在期待某一面了。缺的不是答案，是有个东西帮我把心里那个模糊的念头，变成看得见的画面。

Vibe coding 了一段时间，写了不少东西，但"我到底适合什么岗位"这个问题一直没想清楚。AI 全栈工程这个方向还很新，行业本身也在摸索——市场到底需要什么样的人，岗位边界在哪里，其实没有人说得清楚。每天刷招聘平台，看各种 JD，非常消耗精力。

然后我开始想：

- **市场到底需要什么？** JD 那么多，能不能自动筛选和分析
- **我的技能和市场怎么对应？** 能不能让 AI 帮我梳理清楚
- **哪些岗位真正适合我？** 不是海投，是精准匹配
- **简历该怎么写？** 新时代的简历应该是什么样的
- **投递记录散落各处，能不能统一追踪？**

这些事完全可以让 AI 来做。我本身有另一个项目在做，但那个产品的架构不适合硬塞 RAG、Agent 这些技术。所以开了这个新项目——既解决自己的求职问题，又把想实践的技术真正动手写一遍。

不是让 AI 替我做决定。看到匹配结果的那一刻，心里的反应——"果然如此"还是"不对，我不想要这个"——那个反应本身，就是一直在找的答案。AI 能算匹配度，但算不了我的人生。工具就是工具，看清选项用的。路，还是自己走。

**MooBot 就是这么来的：一头牛马给自己写的求职工具。🐄**

## 这是什么

MooBot 是一个 AI 求职顾问 Agent，帮你分析自身技能、理解市场需求、匹配合适岗位、管理求职流程。

本质上做的是一件事：**让你看清自己和市场之间的关系。**

```
你："帮我找上海 AI 应用开发的岗位，30-50K"

MooBot 执行：
  1. 搜索岗位 → 抓取列表
  2. 解析 JD → 提取技能要求、经验要求、岗位职责
  3. 对比简历 → 分析匹配度，指出差距和优势
  4. 推荐岗位 → 按匹配度排序
  5. 投递 + 记录 → 追踪进度
```

## 特性

- **Agent 架构** — ReAct 模式，LLM 动态决策 + 工具调用
- **记忆系统** — MemoryExtractor 子 Agent 异步提取对话中的用户信息，写入记忆画像文件；下次对话自动加载，Agent 越用越懂你
- **Skills 系统** — Markdown 格式的业务场景剧本（简历生成、面试准备等），动态注入 System Prompt，Agent 按场景执行
- **多 LLM 支持** — OpenAI 兼容格式，支持阿里云 DashScope / OpenAI / Google Gemini / DeepSeek
- **RAG 知识库** — LightRAG 知识图谱 + 向量检索，hybrid 模式融合
- **浏览器自动化** — Playwright 驱动，支持猎聘等平台
- **Web UI** — Chainlit 对话 + 岗位管理 + 简历管理 + 一键求职
- **Tool 可扩展** — 继承基类，注册即用（[开发指南](docs/tool-development.md)）

## 架构

```
用户对话 → Executor.chat() → LLM（function calling）
                                ↓
                        模型决定下一步：
                        ├── 直接回复
                        ├── 调用工具
                        └── 回复 + 调用工具
                                ↓
                        工具结果 → 再调 LLM → 直到完成
```

```
┌─────────────────────────────────────────────┐
│              Web UI (Chainlit + FastAPI)     │
│  对话 │ 岗位管理 │ 简历 │ 一键求职 │ 设置   │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Agent Core                      │
│                                              │
│  Executor (主 Agent Loop)                    │
│    ├── LLM Client (多厂商切换)               │
│    ├── System Prompt (人设 + 记忆指引 + Skills)│
│    └── MemoryExtractor (子 Agent, 异步提取)   │
│                                              │
│  Skill Loader (Markdown 场景剧本)            │
│  Memory (用户偏好 + 黑名单 + 投递历史)        │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Tool Layer                      │
│  数据操作 │ 记忆工具 │ AI 分析 │ 浏览器 │ RAG │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Storage                         │
│  SQLite │ 记忆画像 (Markdown) │ Skills (MD)  │
│  LightRAG 知识图谱 │ 对话历史 (JSONL)         │
└─────────────────────────────────────────────┘
```

## 当前适配状态

> MooBot 处于早期开发阶段，功能和平台适配在持续扩展中。

**招聘平台**

目前仅适配 **猎聘**（中国大陆）。浏览器自动化（岗位搜索、JD 获取、打招呼）的逻辑参考 [get_jobs](https://github.com/loks666/get_jobs) 项目，针对猎聘的页面结构开发。其他平台（Boss 直聘、智联、拉勾等）暂未适配。

**LLM 模型**

项目服务国内求职场景，考虑到网络环境，开发和测试主要使用阿里云 DashScope 的 **通义千问（qwen3.5-flash）**，国内直连、无需翻墙，推荐大家直接使用。同时支持所有 **OpenAI 兼容格式** 的 API：

| 厂商 | 测试状态 | 说明 |
|------|---------|------|
| 阿里云 DashScope（千问） | ✅ 主要测试 | 默认配置，国内直连，推荐使用 |
| OpenAI | ✅ 兼容 | GPT-4o / GPT-4o-mini，需翻墙 |
| Google Gemini | ✅ 兼容 | 通过 OpenAI 兼容端点接入，需翻墙 |
| DeepSeek | ✅ 兼容 | deepseek-chat，国内可用 |
| 其他 OpenAI 兼容服务 | 🔧 理论支持 | 只要提供兼容的 base_url 即可 |

切换 LLM 只需在设置页面修改 API Key、Base URL 和模型名称，无需改代码。

## 快速开始

```bash
git clone https://github.com/Hanyan179/OfferBot.git
cd OfferBot

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r boss-agent/requirements.txt

cd boss-agent
python -m uvicorn web.app:app --host 0.0.0.0 --port 7860
```

打开 http://localhost:7860，在设置页面配置 API Key，开始对话。

详细步骤见 [快速开始](docs/getting-started.md)。

## 多 LLM 配置

默认使用阿里云 DashScope（`qwen3.5-flash`），切换只需改环境变量：

```bash
# OpenAI
export API_BASE_URL="https://api.openai.com/v1"
export DASHSCOPE_API_KEY="sk-xxx"
export DASHSCOPE_LLM_MODEL="gpt-4o"

# DeepSeek
export API_BASE_URL="https://api.deepseek.com/v1"
export DASHSCOPE_API_KEY="sk-xxx"
export DASHSCOPE_LLM_MODEL="deepseek-chat"

# Google Gemini
export API_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
export DASHSCOPE_API_KEY="your-gemini-key"
export DASHSCOPE_LLM_MODEL="gemini-2.0-flash"
```

完整配置项见 [配置说明](docs/configuration.md)。

## Tool 一览

### 已实现

| Tool | 说明 |
|------|------|
| `get_user_profile` | 获取用户档案 |
| `update_user_profile` | 更新用户档案 |
| `query_jobs` | 岗位查询（SQL + 关键词搜索） |
| `rag_query` | 知识图谱检索（LightRAG hybrid） |
| `fetch_job_detail` | 获取岗位详情 |
| `save_job` | 保存岗位数据 |
| `save_application` | 记录投递 |
| `get_stats` | 投递统计 |
| `add_to_blacklist` / `remove_from_blacklist` | 黑名单管理 |
| `export_csv` | 导出 CSV |

### 开发中

- 浏览器：岗位搜索、详情抓取、自动投递

想自己写 Tool？见 [Tool 开发指南](docs/tool-development.md)。

## 项目结构

```
boss-agent/
├── agent/          # Agent 核心（Executor, LLM Client, Memory, MemoryExtractor）
├── db/             # SQLite 数据库
├── rag/            # RAG Pipeline（LightRAG 知识图谱 + 向量检索）
├── tools/          # Tool 层
│   ├── data/       #   数据操作（岗位、投递、统计、黑名单、记忆）
│   ├── ai/         #   AI 分析（JD 解析、匹配）
│   └── browser/    #   浏览器自动化（搜索、投递）
├── skills/         # Markdown 场景剧本（简历生成、面试准备等）
├── web/            # Web UI（FastAPI + Chainlit）
├── tests/          # 测试
├── scripts/        # 脚本
└── data/           # 运行时数据（知识库、简历、索引、记忆画像）
```

## 技术栈与选型理由

| 技术 | 为什么用 |
|---|---|
| **自建 Agent Loop** | 用户说一句话，模型自己决定调哪些工具、按什么顺序执行——求职场景的任务链不固定，需要 LLM 动态决策 |
| **OpenAI SDK** | 统一接口兼容多家 LLM（阿里云/OpenAI/Gemini/DeepSeek），用户按预算和效果自己选 |
| **LightRAG** | 知识图谱 + 向量双模检索，JD 图谱化后支持技能关系匹配、语义问答 |
| **Playwright** | 招聘平台没有开放 API，只能通过浏览器自动化抓取岗位数据 |
| **SQLite** | 单用户本地工具，岗位数据、投递记录、用户档案都存本地，不需要服务端数据库 |
| **Chainlit (fork)** | 对话 UI（流式输出、Markdown、工具调用展示），fork 定制了导航栏和页面嵌入 |
| **FastAPI** | API 路由 + 子页面渲染（岗位、面试、画像、设置等） |

## 我们不做什么

**MooBot 不做面试过程辅助。** 不做模拟面试、不做实时提词、不做 AI 代面。

面试是一个双向的过程——你在了解公司，公司也在了解你。这是真实的人与人之间的沟通和学习，AI 不应该介入这个环节。用 AI 辅助面试过程，本质上是在破坏这种真实性。

MooBot 帮你做的是面试**之前**的事：看清自己、理解市场、找到方向、准备好简历。到了面试，那是你自己的舞台。

## ⚠️ 免责声明与法律合规

### 项目性质

MooBot 是一个**开源学习项目**，浏览器自动化功能仅用于获取招聘平台**公开发布的岗位信息**（职位名称、岗位描述、技能要求、薪资范围等企业主动公开的招聘数据），供个人求职参考和技术学习使用。

### 我们做什么 / 不做什么

| ✅ 做 | ❌ 不做 |
|-------|---------|
| 获取企业主动公开的招聘信息 | 不获取、不存储任何个人隐私数据（HR 私人联系方式、手机号等） |
| 数据仅存储在用户本地 | 不建立数据库对外提供数据服务 |
| 个人求职用途 | 不将数据用于商业竞争或转售 |
| 合理频率访问（每次请求间隔 ≥ 2 秒） | 不大规模高频抓取、不对平台造成服务压力 |
| 建议使用前检查目标平台 robots.txt | 不绕过、不破解平台的安全验证和反爬措施 |

### 法律风险提示

使用本项目前，请知悉以下中国大陆相关法律法规：

- **《刑法》第 285 条**（非法获取计算机信息系统数据罪）— 绕过网站安全措施获取数据可能构成犯罪
- **《个人信息保护法》** — 未经同意收集、存储、传播个人信息属于违法行为
- **《数据安全法》** — 数据收集和使用需遵守合法、正当、必要原则
- **《反不正当竞争法》** — 利用技术手段获取竞争优势可能构成不正当竞争

### 平台使用条款

大多数招聘平台（猎聘、Boss 直聘、智联、拉勾等）的用户协议明确禁止使用脚本、插件或自动化工具。使用浏览器自动化功能可能导致账号被限制或封禁。

### 使用者责任

- 本项目仅提供技术实现，**使用者需自行承担使用后果**
- 使用前请阅读目标平台的用户协议和 robots.txt
- 请将访问频率控制在合理范围内，避免对平台正常运营造成影响
- 如平台明确要求停止自动化访问，请立即停止
- 禁止将本项目用于任何违法违规用途

**本项目作者不对使用者因使用本项目而产生的任何法律责任、经济损失或其他后果承担责任。**

## 路线图

**当前重心：求职工具本身**

把搜索、匹配、投递、追踪这条链路做扎实。

**后续计划：学习与知识分享**

AI 领域变化太快，很多人和我一样在探索自己的方向。后续会加入学习板块——AI 就业方向梳理、技术学习路径、社区资源分享。不是教程网站，是牛马之间的经验交流。

**关于商业化**

这个项目的出发点就是为了自己面试，顺便开源出来。我个人不做商业化。

但从架构上看，这套东西是有商业化空间的。如果做成平台：岗位数据变成自有数据（不依赖抓取），求职端的 AI 分析能力可以做成服务，简历真实性验证、技能认证等方向也有价值。感兴趣的人可以基于这个项目去探索，MIT 协议没有限制。

## 文档

- [快速开始](docs/getting-started.md) — 安装、配置、跑起来
- [配置说明](docs/configuration.md) — LLM 多厂商切换、环境变量一览
- [开发新 Tool](docs/tool-development.md) — 4 步扩展 Agent 能力
- [常见问题](docs/faq.md) — FAQ

## 致谢

MooBot 的浏览器自动化能力参考和借鉴了以下优秀的开源项目：

- **[get_jobs](https://github.com/loks666/get_jobs)** — Boss 直聘 / 猎聘 / 智联 / 前程无忧全平台自动投递工具。MooBot 的岗位搜索、JD 获取、打招呼等浏览器自动化逻辑参考了该项目的 Playwright 实现，感谢 [@loks666](https://github.com/loks666) 的开源贡献。

> ⚠️ get_jobs 使用 **GETJOBS-NC-1.0（非商业许可）**。MooBot 中 `reference-crawler` 目录下的代码源自该项目，**仅限非商业用途**。如需商业使用，请联系 get_jobs 原作者获取授权。

## 贡献

欢迎各位牛马 PR！见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

MooBot 采用双协议：

- **MooBot 核心代码**（`boss-agent/` 目录）— [MIT](LICENSE)，随便用，moo～ 🐄
- **浏览器自动化模块**（`reference-crawler/` 目录）— [GETJOBS-NC-1.0](https://github.com/loks666/get_jobs/blob/main/LICENSE)，源自 get_jobs 项目，**仅限非商业用途**
