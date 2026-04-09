.PHONY: lint format test test-pbt test-agent serve check tool-graph help

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

lint: ## 代码检查（ruff）
	python3 -m ruff check .

format: ## 代码格式化（ruff）
	python3 -m ruff format .

fix: ## 自动修复 lint 问题
	python3 -m ruff check . --fix

test: ## 跑全部单元测试
	python3 -m pytest tests/ -v --tb=short

test-pbt: ## 跑属性测试
	python3 -m pytest tests/ -v -k "pbt" --tb=short

test-agent: ## 跑 Agent 行为测试（需要服务运行）
	python3 scripts/test_agent_chat.py --scenario all

check: ## lint + test 一起跑
	python3 -m ruff check .
	python3 -m pytest tests/ -v --tb=short

tool-graph: ## 生成 Tool 关系图谱
	python3 scripts/tool_graph.py

tool-check: ## Tool 一致性检查
	python3 scripts/tool_graph.py --check

serve: ## 启动开发服务器（手动在终端跑）
	@echo "请在终端手动运行: uvicorn web.app:app --reload --port 7860"
