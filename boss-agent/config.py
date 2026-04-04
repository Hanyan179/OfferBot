"""
配置管理模块

从环境变量读取所有配置项，提供合理的默认值。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


# 项目根目录（boss-agent/）
PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Config:
    """应用配置，从环境变量读取，不可变。"""

    # --- LLM API (OpenAI 兼容格式) ---
    dashscope_api_key: str = ""
    api_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_llm_model: str = "qwen3.5-flash"
    dashscope_embedding_model: str = "text-embedding-v3"
    dashscope_rerank_model: str = "gte-rerank"

    # --- 数据库 ---
    db_path: str = str(PROJECT_ROOT / "db" / "boss_agent.db")

    # --- 日志 ---
    log_level: str = "INFO"

    # --- 匹配分析 ---
    match_threshold: float = 80.0  # 投递匹配度阈值（0-100）
    match_weight_skill: float = 0.4
    match_weight_experience: float = 0.3
    match_weight_responsibility: float = 0.3

    # --- 反检测延迟（秒） ---
    anti_detect_min_delay: float = 2.0
    anti_detect_max_delay: float = 5.0
    apply_min_delay: float = 10.0
    apply_max_delay: float = 30.0

    # --- RAG ---
    rag_chunk_size: int = 768
    rag_chunk_overlap: float = 0.15
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.3

    # --- 知识库 & 索引路径 ---
    knowledge_dir: str = str(PROJECT_ROOT / "data" / "knowledge")
    index_dir: str = str(PROJECT_ROOT / "data" / "index")

    # --- Agent ---
    agent_max_turns: int = 50
    tool_max_retries: int = 3

    # --- Gradio ---
    gradio_host: str = "127.0.0.1"
    gradio_port: int = 7860

    # --- 打招呼语 ---
    greeting_max_length: int = 200

    # --- 记忆系统 ---
    memory_dir: str = str(PROJECT_ROOT / "data" / "记忆画像")
    conversations_dir: str = str(PROJECT_ROOT / "data" / "conversations")
    skills_dir: str = str(PROJECT_ROOT / "skills")
    max_restore_messages: int = 200

    # --- Web Tools ---
    web_fetch_timeout: int = 30
    web_fetch_max_content_length: int = 50000
    web_fetch_cache_ttl: int = 900
    web_search_default_results: int = 10
    web_search_api_key: str = ""


def load_config() -> Config:
    """从环境变量加载配置，缺失项使用默认值。"""
    defaults = Config()

    def _env(key: str, default: str) -> str:
        return os.environ.get(key, default)

    def _env_float(key: str, default: float) -> float:
        raw = os.environ.get(key)
        return float(raw) if raw is not None else default

    def _env_int(key: str, default: int) -> int:
        raw = os.environ.get(key)
        return int(raw) if raw is not None else default

    return Config(
        # LLM API
        dashscope_api_key=_env("DASHSCOPE_API_KEY", defaults.dashscope_api_key),
        api_base_url=_env("API_BASE_URL", defaults.api_base_url),
        dashscope_llm_model=_env("DASHSCOPE_LLM_MODEL", defaults.dashscope_llm_model),
        dashscope_embedding_model=_env("DASHSCOPE_EMBEDDING_MODEL", defaults.dashscope_embedding_model),
        dashscope_rerank_model=_env("DASHSCOPE_RERANK_MODEL", defaults.dashscope_rerank_model),
        # 数据库
        db_path=_env("DB_PATH", defaults.db_path),
        # 日志
        log_level=_env("LOG_LEVEL", defaults.log_level),
        # 匹配
        match_threshold=_env_float("MATCH_THRESHOLD", defaults.match_threshold),
        match_weight_skill=_env_float("MATCH_WEIGHT_SKILL", defaults.match_weight_skill),
        match_weight_experience=_env_float("MATCH_WEIGHT_EXPERIENCE", defaults.match_weight_experience),
        match_weight_responsibility=_env_float("MATCH_WEIGHT_RESPONSIBILITY", defaults.match_weight_responsibility),
        # 反检测
        anti_detect_min_delay=_env_float("ANTI_DETECT_MIN_DELAY", defaults.anti_detect_min_delay),
        anti_detect_max_delay=_env_float("ANTI_DETECT_MAX_DELAY", defaults.anti_detect_max_delay),
        apply_min_delay=_env_float("APPLY_MIN_DELAY", defaults.apply_min_delay),
        apply_max_delay=_env_float("APPLY_MAX_DELAY", defaults.apply_max_delay),
        # RAG
        rag_chunk_size=_env_int("RAG_CHUNK_SIZE", defaults.rag_chunk_size),
        rag_chunk_overlap=_env_float("RAG_CHUNK_OVERLAP", defaults.rag_chunk_overlap),
        rag_top_k=_env_int("RAG_TOP_K", defaults.rag_top_k),
        rag_similarity_threshold=_env_float("RAG_SIMILARITY_THRESHOLD", defaults.rag_similarity_threshold),
        # 路径
        knowledge_dir=_env("KNOWLEDGE_DIR", defaults.knowledge_dir),
        index_dir=_env("INDEX_DIR", defaults.index_dir),
        # Agent
        agent_max_turns=_env_int("AGENT_MAX_TURNS", defaults.agent_max_turns),
        tool_max_retries=_env_int("TOOL_MAX_RETRIES", defaults.tool_max_retries),
        # Gradio
        gradio_host=_env("GRADIO_HOST", defaults.gradio_host),
        gradio_port=_env_int("GRADIO_PORT", defaults.gradio_port),
        # 打招呼语
        greeting_max_length=_env_int("GREETING_MAX_LENGTH", defaults.greeting_max_length),
        # 记忆系统
        memory_dir=_env("MEMORY_DIR", defaults.memory_dir),
        conversations_dir=_env("CONVERSATIONS_DIR", defaults.conversations_dir),
        skills_dir=_env("SKILLS_DIR", defaults.skills_dir),
        max_restore_messages=_env_int("MAX_RESTORE_MESSAGES", defaults.max_restore_messages),
        # Web Tools
        web_fetch_timeout=_env_int("WEB_FETCH_TIMEOUT", defaults.web_fetch_timeout),
        web_fetch_max_content_length=_env_int("WEB_FETCH_MAX_CONTENT_LENGTH", defaults.web_fetch_max_content_length),
        web_fetch_cache_ttl=_env_int("WEB_FETCH_CACHE_TTL", defaults.web_fetch_cache_ttl),
        web_search_default_results=_env_int("WEB_SEARCH_DEFAULT_RESULTS", defaults.web_search_default_results),
        web_search_api_key=_env("WEB_SEARCH_API_KEY", defaults.web_search_api_key),
    )
