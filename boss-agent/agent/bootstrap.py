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
from tools.getjob.fetch_detail import FetchJobDetailTool
from tools.getjob.platform_config import PlatformGetConfigTool, PlatformUpdateConfigTool
from tools.getjob.platform_control import PlatformStartTaskTool, PlatformStopTaskTool
from tools.getjob.platform_deliver import PlatformDeliverTool
from tools.getjob.platform_stats import PlatformStatsTool

# Getjob Tools
from tools.getjob.platform_status import PlatformStatusTool
from tools.getjob.platform_sync import SyncJobsTool
from tools.getjob.service_manager import GetjobServiceManagerTool


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

    # --- Getjob Tools ---
    registry.register(PlatformStatusTool())
    registry.register(PlatformStartTaskTool())
    registry.register(PlatformStopTaskTool())
    registry.register(PlatformGetConfigTool())
    registry.register(PlatformUpdateConfigTool())
    registry.register(SyncJobsTool())
    registry.register(PlatformStatsTool())
    registry.register(GetjobServiceManagerTool())
    registry.register(FetchJobDetailTool())
    registry.register(PlatformDeliverTool())

    # --- AI Tools ---
    skill_loader = SkillLoader(registry=registry)
    registry.register(GetSkillContentTool(skill_loader))

    # --- Meta Tools (toolset routing) ---
    registry.register(ActivateToolsetTool())
    registry.register(GetDataStatusTool())

    return registry, skill_loader


def bootstrap(db: Database, api_key: str, model: str = "qwen-plus", base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1", getjob_base_url: str = "http://localhost:8888") -> dict:
    """
    完整的应用启动引导。

    Returns:
        dict with keys: registry, planner, executor, getjob_client
    """
    from agent.executor import Executor
    from agent.llm_client import LLMClient
    from agent.planner import Planner
    from services.getjob_client import GetjobClient

    registry, skill_loader = create_tool_registry()
    llm_client = LLMClient(api_key=api_key, model=model, base_url=base_url)
    getjob_client = GetjobClient(base_url=getjob_base_url)

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
        "getjob_client": getjob_client,
        "skill_loader": skill_loader,
    }
