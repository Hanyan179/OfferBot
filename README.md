# 🤖 OfferBot

AI 驱动的求职自动化 Agent，覆盖求职全流程：简历优化、岗位搜索、JD 解析、匹配分析、自动投递、面试追踪。

## 特性

- **ReAct Agent 架构** — 参考 Claude Code 的 Agent Loop 设计，LLM 动态决策 + 工具调用
- **多 LLM 支持** — OpenAI 兼容格式，支持阿里云 DashScope、OpenAI、Google Gemini、DeepSeek 等
- **RAG 知识库** — FAISS 向量检索 + BM25 关键词检索 + RRF 融合 + Rerank
- **浏览器自动化** — Playwright 驱动，反检测策略，支持 Boss 直聘等平台
- **单页面 Web UI** — 对话驱动 + 岗位管理 + 简历管理 + 面试追踪 + 徽章墙

## 技术栈

Python 3.11+ / FastAPI / Chainlit / Playwright / OpenAI SDK / FAISS / SQLite

## 快速开始

```bash
# 克隆
git clone https://github.com/Hanyan179/OfferBot.git
cd OfferBot

# 安装依赖
python -m venv .venv
source .venv/bin/activate
pip install -r boss-agent/requirements.txt

# 启动
cd boss-agent
python -m uvicorn web.app:app --host 0.0.0.0 --port 7860

# 打开 http://localhost:7860，在设置页面配置 API Key
```

## 项目结构

```
boss-agent/
├── agent/          # Agent 核心（Planner, Executor, LLM Client）
├── db/             # SQLite 数据库
├── rag/            # RAG Pipeline
├── tools/          # Tool 层（浏览器、AI 分析、数据操作）
├── web/            # Web UI（FastAPI + Chainlit）
├── tests/          # 测试
├── scripts/        # 脚本
└── data/           # 运行时数据（知识库、简历、索引）
```

## License

MIT
