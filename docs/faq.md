# 常见问题

## 支持哪些 LLM？

任何兼容 OpenAI API 格式的模型都可以。已验证：

- 阿里云 DashScope（通义千问系列）
- OpenAI（GPT-4o 等）
- Google Gemini
- DeepSeek

通过 `API_BASE_URL` 和 `DASHSCOPE_LLM_MODEL` 两个环境变量切换，详见 [配置说明](configuration.md)。

## 数据存在哪里？

全部存在本地 SQLite 文件（`boss-agent/db/boss_agent.db`），不上传任何数据到云端。

## 可以不用阿里云 DashScope 吗？

可以。环境变量名虽然叫 `DASHSCOPE_API_KEY`，但实际上是通用的 OpenAI 兼容 API Key，配合 `API_BASE_URL` 可以指向任何兼容端点。

## 浏览器自动化功能可以用了吗？

浏览器自动化（Playwright 驱动的岗位搜索、自动投递等）目前还在开发中。当前可用的是对话交互 + 数据管理功能。

## 如何贡献？

参见 [CONTRIBUTING.md](../CONTRIBUTING.md)。
