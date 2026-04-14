# 快速开始

## 环境要求

- Python 3.11+
- 一个 LLM API Key（阿里云 DashScope / OpenAI / Google Gemini / DeepSeek 任选）

## 安装

```bash
git clone https://github.com/Hanyan179/OfferBot.git
cd OfferBot

python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装 Chainlit Fork（定制版 UI，必须先装）
git clone https://github.com/Hanyan179/chainlit.git chainlit-fork
cd chainlit-fork && git checkout custom-dev && cd ..
pip install -e chainlit-fork/backend
ln -s ../../backend/chainlit/frontend/dist/assets chainlit-fork/frontend/dist/assets

# 安装项目依赖
pip install -r boss-agent/requirements.txt
```

## 配置 API Key

两种方式，任选其一：

**方式一：环境变量**

```bash
export DASHSCOPE_API_KEY="your-api-key"
```

**方式二：Web UI 设置页面**

启动后在浏览器的「设置」标签页中填写，保存到本地 SQLite，无需环境变量。

## 启动

```bash
cd boss-agent
python3 -m uvicorn web.app:app --host 0.0.0.0 --port 7860
```

打开 [http://localhost:7860](http://localhost:7860)，开始对话。

## 切换 LLM 厂商

默认使用阿里云 DashScope（`qwen3.5-flash`）。切换到其他厂商只需改两个环境变量：

```bash
# OpenAI
export API_BASE_URL="https://api.openai.com/v1"
export DASHSCOPE_API_KEY="sk-xxx"
export DASHSCOPE_LLM_MODEL="gpt-4o"

# DeepSeek
export API_BASE_URL="https://api.deepseek.com/v1"
export DASHSCOPE_API_KEY="sk-xxx"
export DASHSCOPE_LLM_MODEL="deepseek-chat"
```

更多配置项见 [配置说明](configuration.md)。
