"""
Tests for RAG_SEARCH_STRATEGY integration in system_prompt.

Validates:
- RAG_SEARCH_STRATEGY constant contains all 13 scenario routes (S1-S13)
- build_full_system_prompt() replaces placeholder with actual strategy
- No references to deprecated search_jobs_semantic
- Hard rules (no fabrication, real URLs) are preserved
- Routing rules are complete and correct
- query_jobs scenarios (S2, S6) are properly defined
- Operation scenarios (S12 deliver, S13 tracking) are defined
"""

import pytest

from agent.system_prompt import (
    RAG_SEARCH_STRATEGY,
    SYSTEM_PROMPT,
    build_full_system_prompt,
)


# ---------------------------------------------------------------------------
# 1. RAG_SEARCH_STRATEGY 常量内容完整性
# ---------------------------------------------------------------------------


class TestRAGSearchStrategyConstant:
    """RAG_SEARCH_STRATEGY should define all scenario routes."""

    def test_contains_rag_query_tool(self):
        assert "rag_query" in RAG_SEARCH_STRATEGY

    def test_contains_query_jobs_tool(self):
        assert "query_jobs" in RAG_SEARCH_STRATEGY

    # --- rag_query 场景 (answer mode) ---

    def test_s1_profile_match(self):
        """S1: 画像匹配推荐 → rag_query(mode='answer')"""
        assert "画像匹配推荐" in RAG_SEARCH_STRATEGY
        assert "get_user_profile" in RAG_SEARCH_STRATEGY

    def test_s4_match_analysis(self):
        """S4: 匹配度分析 → rag_query(mode='answer')"""
        assert "匹配度分析" in RAG_SEARCH_STRATEGY

    def test_s5_knowledge_qa(self):
        """S5: 知识问答 → rag_query(mode='answer')"""
        assert "知识问答" in RAG_SEARCH_STRATEGY

    def test_s7_skill_gap(self):
        """S7: 技能差距分析 → rag_query(mode='answer')"""
        assert "技能差距分析" in RAG_SEARCH_STRATEGY

    def test_s8_market_trend(self):
        """S8: 市场趋势 → rag_query(mode='answer')"""
        assert "市场趋势" in RAG_SEARCH_STRATEGY

    def test_s9_batch_compare(self):
        """S9: 批量对比 → rag_query(mode='answer')"""
        assert "批量对比" in RAG_SEARCH_STRATEGY

    def test_s10_resume_customize(self):
        """S10: 简历定制 → rag_query(mode='answer')"""
        assert "简历定制" in RAG_SEARCH_STRATEGY

    def test_s11_interview_prep(self):
        """S11: 面试准备 → rag_query(mode='answer')"""
        assert "面试准备" in RAG_SEARCH_STRATEGY

    # --- rag_query 场景 (search mode) ---

    def test_s3_similar_recommend(self):
        """S3: 相似推荐 → rag_query(mode='search')"""
        assert "相似推荐" in RAG_SEARCH_STRATEGY
        assert 'mode="search"' in RAG_SEARCH_STRATEGY

    # --- query_jobs 场景 ---

    def test_s2_condition_filter(self):
        """S2: 条件筛选 → query_jobs"""
        assert "条件筛选" in RAG_SEARCH_STRATEGY

    def test_s6_exact_search(self):
        """S6: 精确查找 → query_jobs"""
        assert "精确查找" in RAG_SEARCH_STRATEGY

    # --- 操作类场景 ---

    def test_s12_deliver(self):
        """S12: 投递打招呼 → 组合调用"""
        assert "投递打招呼" in RAG_SEARCH_STRATEGY
        assert "platform_deliver" in RAG_SEARCH_STRATEGY

    def test_s13_tracking(self):
        """S13: 投递追踪 → get_interview_funnel / get_stats"""
        assert "投递追踪" in RAG_SEARCH_STRATEGY
        assert "get_interview_funnel" in RAG_SEARCH_STRATEGY
        assert "get_stats" in RAG_SEARCH_STRATEGY

    # --- mode 值定义 ---

    def test_answer_mode_defined(self):
        assert 'mode="answer"' in RAG_SEARCH_STRATEGY

    def test_search_mode_defined(self):
        assert 'mode="search"' in RAG_SEARCH_STRATEGY


# ---------------------------------------------------------------------------
# 2. 路由判断规则
# ---------------------------------------------------------------------------


class TestRoutingRules:
    """Routing rules should be complete and correct."""

    def test_has_routing_section(self):
        assert "路由判断规则" in RAG_SEARCH_STRATEGY

    def test_structured_filter_to_query_jobs(self):
        """具体筛选条件 → query_jobs"""
        # 规则 1: 城市、薪资、公司名 → query_jobs
        assert "城市" in RAG_SEARCH_STRATEGY
        assert "薪资" in RAG_SEARCH_STRATEGY
        assert "公司名" in RAG_SEARCH_STRATEGY

    def test_semantic_to_rag_query(self):
        """语义理解类 → rag_query"""
        # 规则 2: 适合我的、匹配度、推荐、类似的 → rag_query
        for keyword in ["适合我的", "匹配度", "推荐", "类似的", "差距", "趋势"]:
            assert keyword in RAG_SEARCH_STRATEGY, f"Missing routing keyword: {keyword}"

    def test_fallback_to_rag_query(self):
        """不确定时优先 rag_query"""
        assert "不确定时" in RAG_SEARCH_STRATEGY
        assert "优先" in RAG_SEARCH_STRATEGY

    def test_delivery_tracking_route(self):
        """投递进度 → get_interview_funnel / get_stats"""
        assert "投递进度" in RAG_SEARCH_STRATEGY


# ---------------------------------------------------------------------------
# 3. 硬性规则（不编造 + 真实 URL）
# ---------------------------------------------------------------------------


class TestHardRules:
    """Hard rules for data integrity must be present."""

    def test_no_fabrication_rule(self):
        assert "禁止凭空编造岗位信息" in RAG_SEARCH_STRATEGY

    def test_real_url_rule(self):
        assert "真实 url" in RAG_SEARCH_STRATEGY

    def test_url_format_hint(self):
        assert "[岗位名](url)" in RAG_SEARCH_STRATEGY


# ---------------------------------------------------------------------------
# 4. build_full_system_prompt() 集成
# ---------------------------------------------------------------------------


class TestBuildFullSystemPrompt:
    """build_full_system_prompt() should produce a complete prompt."""

    def test_placeholder_replaced(self):
        """Placeholder {rag_search_strategy} must not appear in output."""
        prompt = build_full_system_prompt()
        assert "{rag_search_strategy}" not in prompt

    def test_rag_strategy_injected(self):
        """RAG strategy content should appear in the built prompt."""
        prompt = build_full_system_prompt()
        assert "rag_query" in prompt
        assert "知识图谱检索" in prompt
        assert "路由判断规则" in prompt

    def test_no_search_jobs_semantic(self):
        """Deprecated search_jobs_semantic must not appear anywhere."""
        prompt = build_full_system_prompt()
        assert "search_jobs_semantic" not in prompt

    def test_memory_section_present(self):
        """Memory prompt section should still be included."""
        prompt = build_full_system_prompt()
        assert "记忆系统" in prompt

    def test_skills_section_appended(self):
        """Skills section should be appended when provided."""
        skills = "\n## 可用 Skills\n- 简历生成\n"
        prompt = build_full_system_prompt(skills_prompt_section=skills)
        assert "可用 Skills" in prompt
        assert "简历生成" in prompt

    def test_skills_section_omitted_when_empty(self):
        """Empty skills section should not add extra content."""
        prompt_no_skills = build_full_system_prompt()
        prompt_empty = build_full_system_prompt(skills_prompt_section="")
        assert prompt_no_skills == prompt_empty

    def test_all_13_scenarios_in_full_prompt(self):
        """All 13 scenario keywords should appear in the final prompt."""
        prompt = build_full_system_prompt()
        scenarios = [
            "画像匹配推荐",  # S1
            "条件筛选",      # S2
            "相似推荐",      # S3
            "匹配度分析",    # S4
            "知识问答",      # S5
            "精确查找",      # S6
            "技能差距分析",  # S7
            "市场趋势",      # S8
            "批量对比",      # S9
            "简历定制",      # S10
            "面试准备",      # S11
            "投递打招呼",    # S12
            "投递追踪",      # S13
        ]
        for s in scenarios:
            assert s in prompt, f"Scenario missing from full prompt: {s}"


# ---------------------------------------------------------------------------
# 5. SYSTEM_PROMPT 模板本身
# ---------------------------------------------------------------------------


class TestSystemPromptTemplate:
    """SYSTEM_PROMPT template should have the placeholder, not hardcoded strategy."""

    def test_has_placeholder(self):
        assert "{rag_search_strategy}" in SYSTEM_PROMPT

    def test_no_search_jobs_semantic_in_template(self):
        assert "search_jobs_semantic" not in SYSTEM_PROMPT
