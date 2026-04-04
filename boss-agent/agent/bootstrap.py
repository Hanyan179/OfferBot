"""
应用启动引导 — 注册所有已实现的 Tool 到 ToolRegistry

在应用启动时调用 bootstrap() 完成：
1. 创建 ToolRegistry 实例
2. 注册所有 Data Tools
3. 返回就绪的 registry
"""

from __future__ import annotations

from agent.tool_registry import ToolRegistry
from db.database import Database

# Data Tools
from tools.data.job_store import SaveJobTool
from tools.data.application_store import SaveApplicationTool
from tools.data.interview_tracker import (
    GetInterviewFunnelTool,
    UpdateInterviewStatusTool,
)
from tools.data.stats import GetStatsTool
from tools.data.blacklist import AddToBlacklistTool, RemoveFromBlacklistTool
from tools.data.export import ExportCSVTool
from tools.data.user_profile import GetUserProfileTool, UpdateUserProfileTool

# Memory Tools
from tools.data.memory_tools import (
    SaveMemoryTool,
    GetMemoryTool,
    SearchMemoryTool,
    UpdateMemoryTool,
    DeleteMemoryTool,
    ListMemoryCategoryTool,
    GetUserCognitiveModelTool,
)

# Browser Tools
from tools.browser.web_fetch import WebFetchTool
from tools.browser.web_search import WebSearchTool


def create_tool_registry() -> ToolRegistry:
    """创建 ToolRegistry 并注册所有已实现的 Tool。"""
    registry = ToolRegistry()

    # --- Data Tools ---
    registry.register(SaveJobTool())
    registry.register(SaveApplicationTool())
    registry.register(UpdateInterviewStatusTool())
    registry.register(GetInterviewFunnelTool())
    registry.register(GetStatsTool())
    registry.register(AddToBlacklistTool())
    registry.register(RemoveFromBlacklistTool())
    registry.register(ExportCSVTool())
    registry.register(GetUserProfileTool())
    registry.register(UpdateUserProfileTool())

    # --- Memory Tools ---
    registry.register(SaveMemoryTool())
    registry.register(GetMemoryTool())
    registry.register(SearchMemoryTool())
    registry.register(UpdateMemoryTool())
    registry.register(DeleteMemoryTool())
    registry.register(ListMemoryCategoryTool())
    registry.register(GetUserCognitiveModelTool())

    # --- Browser Tools ---
    registry.register(WebFetchTool())
    registry.register(WebSearchTool())

    return registry


def bootstrap(db: Database, api_key: str, model: str = "qwen-plus", base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1") -> dict:
    """
    完整的应用启动引导。

    Returns:
        dict with keys: registry, planner, executor
    """
    from agent.llm_client import LLMClient
    from agent.planner import Planner
    from agent.executor import Executor

    registry = create_tool_registry()
    llm_client = LLMClient(api_key=api_key, model=model, base_url=base_url)

    planner = Planner(
        tool_registry=registry,
        llm_client=llm_client,
    )

    executor = Executor(
        tool_registry=registry,
        llm_client=llm_client,
    )

    return {
        "registry": registry,
        "planner": planner,
        "executor": executor,
    }
