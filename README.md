# 🤖 OfferBot

**AI 求职顾问 Agent — 帮你看清自己的技能、理解市场需求、找到匹配的方向。**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)

[快速开始](docs/getting-started.md) · [配置说明](docs/configuration.md) · [Tool 开发](docs/tool-development.md) · [FAQ](docs/faq.md) · [贡献指南](CONTRIBUTING.md)

---

## 为什么做这个

我自己在找 AI 方向的工作。

Vibe coding 了一段时间，写了不少东西，但"我到底适合什么岗位"这个问题一直没想清楚。AI 全栈工程这个方向还很新，行业本身也在摸索——市场到底需要什么样的人，岗位边界在哪里，其实没有人说得清楚。每天刷招聘平台，看各种 JD，非常消耗精力。

然后我开始想：

- **市场到底需要什么？** JD 那么多，能不能自动筛选和分析
- **我的技能和市场怎么对应？** 能不能让 AI 帮我梳理清楚
- **哪些岗位真正适合我？** 不是海投，是精准匹配
- **简历该怎么写？** 新时代的简历应该是什么样的
- **投递记录散落各处，能不能统一追踪？**

这些事完全可以让 AI 来做。我本身有另一个项目在做，但那个产品的架构不适合硬塞 RAG、Agent 这些技术。所以开了这个新项目——既解决自己的求职问题，又把想实践的技术真正动手写一遍。

**OfferBot 就是这么来的：一个求职者给自己写的工具。**

## 这是什么

OfferBot 是一个 AI Agent，帮你分析自身技能、理解市场需求、匹配合适岗位、管理求职流程。

本质上做的是一件事：**让你看清自己和市场之间的关系。**

```
你："帮我找上海 AI 应用开发的岗位，30-50K"

OfferBot 执行：
  1. 搜索岗位 → 抓取列表
  2. 解析 JD → 提取技能要求、经验要求、岗位职责
  3. 对比简历 → 分析匹配度，指出差距和优势
  4. 推荐岗位 → 按匹配度排序
  5. 投递 + 记录 → 追踪进度
```

## 特性

- **Agent 架构** — ReAct 模式，LLM 动态决策 + 工具调用
- **多 LLM 支持** — OpenAI 兼容格式，支持阿里云 DashScope / OpenAI / Google Gemini / DeepSeek
- **RAG 知识库** — FAISS 向量检索 + BM25 关键词检索 + RRF 融合 + Rerank
- **浏览器自动化** — Playwright 驱动，支持 Boss 直聘等平台（开发中）
- **Web UI** — 对话 + 岗位管理 + 简历管理 + 面试追踪
- **Tool 可扩展** — 继承基类，注册即用（[开发指南](docs/tool-development.md)）
- **本地存储** — SQLite，数据不上传

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
│              Web UI (FastAPI + Chainlit)     │
│  对话 │ 岗位管理 │ 简历 │ 面试追踪 │ 设置   │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Agent Core                      │
│  Executor + Planner + Memory + LLM Client    │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Tool Layer                      │
│  数据操作 │ AI 分析 │ 浏览器自动化 │ RAG     │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Storage                         │
│  SQLite │ FAISS 向量索引 │ 知识库文档         │
└─────────────────────────────────────────────┘
```

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
| `save_job` | 保存岗位数据 |
| `save_application` | 记录投递 |
| `get_stats` | 投递统计 |
| `get_interview_funnel` | 面试漏斗 |
| `update_interview_status` | 更新面试状态 |
| `add_to_blacklist` / `remove_from_blacklist` | 黑名单管理 |
| `export_csv` | 导出 CSV |

### 开发中

- AI 分析：JD 解析、简历匹配
- RAG：知识库检索
- 浏览器：岗位搜索、详情抓取、自动投递

想自己写 Tool？见 [Tool 开发指南](docs/tool-development.md)。

## 项目结构

```
boss-agent/
├── agent/          # Agent 核心（Executor, Planner, LLM Client, Memory）
├── db/             # SQLite 数据库
├── rag/            # RAG Pipeline（Embedding, 索引, 检索, Rerank）
├── tools/          # Tool 层
│   ├── data/       #   数据操作（岗位、投递、统计、黑名单）
│   ├── ai/         #   AI 分析（JD 解析、匹配）
│   └── browser/    #   浏览器自动化（搜索、投递）
├── web/            # Web UI（FastAPI + Chainlit）
├── tests/          # 测试
├── scripts/        # 脚本
└── data/           # 运行时数据（知识库、简历、索引）
```

## 技术栈

| 层 | 技术 |
|---|---|
| 语言 | Python 3.11+ |
| Agent | 自建 Agent Loop |
| LLM | OpenAI SDK（兼容多厂商） |
| UI | FastAPI + Chainlit |
| 浏览器 | Playwright |
| 向量检索 | FAISS + BM25 + RRF |
| 数据库 | SQLite + aiosqlite |

## 路线图

**当前重心：求职工具本身**

把搜索、匹配、投递、追踪这条链路做扎实。

**后续计划：学习与知识分享**

AI 领域变化太快，很多人和我一样在探索自己的方向。后续会加入学习板块——AI 就业方向梳理、技术学习路径、社区资源分享。不是教程网站，是求职者之间的经验交流。

## 文档

- [快速开始](docs/getting-started.md) — 安装、配置、跑起来
- [配置说明](docs/configuration.md) — LLM 多厂商切换、环境变量一览
- [开发新 Tool](docs/tool-development.md) — 4 步扩展 Agent 能力
- [常见问题](docs/faq.md) — FAQ

## 贡献

欢迎 PR！见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

[MIT](LICENSE)
