# 配置说明

所有配置通过环境变量读取，缺失项使用默认值。

## LLM API

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DASHSCOPE_API_KEY` | — | API Key（必填） |
| `API_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | API 地址 |
| `DASHSCOPE_LLM_MODEL` | `qwen3.5-flash` | 对话模型 |
| `DASHSCOPE_EMBEDDING_MODEL` | `text-embedding-v3` | Embedding 模型 |
| `DASHSCOPE_RERANK_MODEL` | `gte-rerank` | Rerank 模型 |

## 多厂商配置示例

```bash
# 阿里云 DashScope（默认）
export DASHSCOPE_API_KEY="sk-xxx"

# OpenAI
export API_BASE_URL="https://api.openai.com/v1"
export DASHSCOPE_API_KEY="sk-xxx"
export DASHSCOPE_LLM_MODEL="gpt-4o"

# Google Gemini（OpenAI 兼容端点）
export API_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
export DASHSCOPE_API_KEY="your-gemini-key"
export DASHSCOPE_LLM_MODEL="gemini-2.0-flash"

# DeepSeek
export API_BASE_URL="https://api.deepseek.com/v1"
export DASHSCOPE_API_KEY="sk-xxx"
export DASHSCOPE_LLM_MODEL="deepseek-chat"
```

## 数据库

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DB_PATH` | `boss-agent/db/boss_agent.db` | SQLite 数据库路径 |

## RAG

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `RAG_CHUNK_SIZE` | `768` | 文档切片大小 |
| `RAG_CHUNK_OVERLAP` | `0.15` | 切片重叠比例 |
| `RAG_TOP_K` | `5` | 检索返回数量 |
| `RAG_SIMILARITY_THRESHOLD` | `0.3` | 相似度阈值 |
| `KNOWLEDGE_DIR` | `boss-agent/data/knowledge` | 知识库文档目录 |
| `INDEX_DIR` | `boss-agent/data/index` | 向量索引目录 |

## Agent

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `AGENT_MAX_TURNS` | `50` | Agent Loop 最大轮次 |
| `TOOL_MAX_RETRIES` | `3` | Tool 执行失败重试次数 |

## 其他

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `GRADIO_HOST` | `0.0.0.0` | 服务监听地址 |
| `GRADIO_PORT` | `7860` | 服务端口 |
| `GREETING_MAX_LENGTH` | `200` | 打招呼语最大字数 |
