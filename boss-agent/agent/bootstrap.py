"""
应用启动引导 — 注册所有已实现的 Tool 到 ToolRegistry

在应用启动时调用 bootstrap() 完成：
1. 创建 ToolRegistry 实例
2. 注册所有 Data Tools
3. 返回就绪的 registry
"""

from __future__ import annotations

# AI Tools
from agent.skill_loader import SkillLoader
from agent.tool_registry import ToolRegistry
from db.database import Database
from tools.ai.get_skill_content import GetSkillContentTool

# Meta Tools (toolset routing)
from tools.meta.activate_toolset import ActivateToolsetTool
from tools.meta.get_data_status import GetDataStatusTool

# Browser Tools (Web)
from tools.browser.web_fetch import WebFetchTool
from tools.browser.web_search import WebSearchTool
from tools.data.application_store import SaveApplicationTool
from tools.data.export import ExportCSVTool
from tools.data.job_manage import DeleteJobsTool, JobCountTool

# Data Tools
from tools.data.job_store import SaveJobTool

# Memory Tools
from tools.data.memory_tools import (
    DeleteMemoryTool,
    GetMemoryTool,
    GetUserCognitiveModelTool,
    SaveMemoryTool,
    SearchMemoryTool,
    UpdateMemoryTool,
)

# Query Tools
from tools.data.query_jobs import QueryJobsTool
from tools.data.stats import GetStatsTool
from tools.data.user_profile import GetUserProfileTool, UpdateUserProfileTool
from tools.crawler.scrape_jobs import ScrapeJobsTool
from tools.crawler.fetch_detail import FetchDetailTool
from tools.crawler.deliver import DeliverTool


def create_tool_registry() -> tuple[ToolRegistry, SkillLoader]:
    """创建 ToolRegistry 并注册所有已实现的 Tool。

    Returns:
        (registry, skill_loader) 元组
    """
    registry = ToolRegistry()

    # --- Data Tools ---
    registry.register(SaveJobTool())
    registry.register(SaveApplicationTool())
    registry.register(GetStatsTool())
    registry.register(ExportCSVTool())
    registry.register(GetUserProfileTool())
    registry.register(UpdateUserProfileTool())
    registry.register(QueryJobsTool())
    registry.register(DeleteJobsTool())
    registry.register(JobCountTool())

    # --- Memory Tools ---
    registry.register(SaveMemoryTool())
    registry.register(GetMemoryTool())
    registry.register(SearchMemoryTool())
    registry.register(UpdateMemoryTool())
    registry.register(DeleteMemoryTool())
    registry.register(GetUserCognitiveModelTool())

    # --- Browser Tools (Web) ---
    registry.register(WebFetchTool())
    registry.register(WebSearchTool())

    # --- Crawler Tools (Playwright) ---
    registry.register(ScrapeJobsTool())
    registry.register(FetchDetailTool())
    registry.register(DeliverTool())

    # --- AI Tools ---
    skill_loader = SkillLoader(registry=registry)
    registry.register(GetSkillContentTool(skill_loader))

    # --- Meta Tools (toolset routing) ---
    registry.register(ActivateToolsetTool())
    registry.register(GetDataStatusTool())

    return registry, skill_loader


def bootstrap(db: Database, api_key: str, model: str = "qwen-plus", base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1") -> dict:
    """
    完整的应用启动引导。

    Returns:
        dict with keys: registry, planner, executor, skill_loader
    """
    from agent.executor import Executor
    from agent.llm_client import LLMClient
    from agent.planner import Planner

    registry, skill_loader = create_tool_registry()
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
        "skill_loader": skill_loader,
    }
