# 🤖 OfferBot

**AI 求职顾问 Agent — 不是聊天机器人，是真正帮你完成求职任务的工具。**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)

[快速开始](docs/getting-started.md) · [配置说明](docs/configuration.md) · [Tool 开发](docs/tool-development.md) · [FAQ](docs/faq.md) · [贡献指南](CONTRIBUTING.md)

---

## 这是什么

OfferBot 是一个执行型 AI Agent，覆盖求职全流程。你告诉它你想找什么工作，它帮你搜索、分析、匹配、投递、追踪。

核心理念：**模型是大脑，我们开发的是手脚（Tools）和记忆（数据库）。**

```
你："帮我找上海 AI 应用开发的岗位，30-50K"

OfferBot 自动执行：
  1. 搜索岗位 → 抓取列表
  2. 解析 JD → 提取技能/经验/职责
  3. 匹配简历 → Embedding + LLM 评分
  4. 生成打招呼语 → 个性化
  5. 自动投递 → 记录结果
  6. 输出报告 → "已投递 X 个，匹配度最高的是 XXX"
```

## 特性

- **ReAct Agent 架构** — 参考 Claude Code 的 Agent Loop 设计，LLM 动态决策 + 工具调用，不用 LangChain/LangGraph
- **多 LLM 支持** — OpenAI 兼容格式，通过 `base_url` 切换：阿里云 DashScope / OpenAI / Google Gemini / DeepSeek
- **RAG 知识库** — FAISS 向量检索 + BM25 关键词检索 + RRF 融合 + Rerank
- **浏览器自动化** — Playwright 驱动，反检测策略，支持 Boss 直聘等平台（开发中）
- **单页面 Web UI** — 对话驱动 + 岗位管理 + 简历管理 + 面试追踪 + 徽章墙
- **Tool 可扩展** — 继承 `Tool` 基类，4 步注册，模型自动调用（[开发指南](docs/tool-development.md)）
- **全本地存储** — SQLite，数据不上传云端

## 架构

```
用户对话 → Executor.chat() → LLM（function calling）
                                ↓
                        模型自己决定：
                        ├── 纯文本回复（聊天）
                        ├── 调用工具（操作数据）
                        └── 文本 + 工具（边聊边存）
                                ↓
                        工具结果 → 再调 LLM → 直到只回复文本
```

```
┌─────────────────────────────────────────────┐
│              Web UI (FastAPI + Chainlit)     │
│  对话 │ 岗位管理 │ 简历 │ 面试追踪 │ 设置   │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Agent Core                      │
│  Executor (Agent Loop) + Planner + Memory    │
│  LLM Client (OpenAI 兼容, 多厂商切换)        │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Tool Layer                      │
│  数据操作 │ AI 分析 │ 浏览器自动化 │ RAG     │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Storage                         │
│  SQLite (WAL) │ FAISS 向量索引 │ 知识库文档  │
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
| `update_user_profile` | 更新用户档案（对话中静默调用） |
| `save_job` | 保存岗位数据 |
| `save_application` | 记录投递 |
| `get_stats` | 投递统计 |
| `get_interview_funnel` | 面试漏斗 |
| `update_interview_status` | 更新面试状态 |
| `add_to_blacklist` / `remove_from_blacklist` | 黑名单管理 |
| `export_csv` | 导出 CSV |

### 开发中

- AI 分析：JD 解析、简历匹配、打招呼语生成
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
│   ├── ai/         #   AI 分析（JD 解析、匹配、打招呼语）
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
| Agent | 自建 Agent Loop（参考 Claude Code） |
| LLM | OpenAI SDK（兼容多厂商） |
| UI | FastAPI + Chainlit |
| 浏览器 | Playwright |
| 向量检索 | FAISS + BM25 + RRF |
| 数据库 | SQLite + aiosqlite |

## 文档

- [快速开始](docs/getting-started.md) — 安装、配置、跑起来
- [配置说明](docs/configuration.md) — LLM 多厂商切换、环境变量一览
- [开发新 Tool](docs/tool-development.md) — 4 步扩展 Agent 能力
- [常见问题](docs/faq.md) — FAQ

## 贡献

欢迎 PR！见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

[MIT](LICENSE)
