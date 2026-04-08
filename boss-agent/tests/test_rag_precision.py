"""
Unit tests for LightRAG 检索精准度调优 — 规范化规则完整性.

验证 _patch_extraction_prompt() patch 后 prompt 包含所有新增规则关键词，
并保留了现有规则。
需求: 3.6
"""

from __future__ import annotations

from unittest.mock import patch


class TestPatchExtractionPromptRules:
    """验证 _patch_extraction_prompt 规范化规则完整性。"""

    def _get_patched_prompt(self) -> str:
        """Mock PROMPTS dict, call _patch_extraction_prompt, return patched prompt."""
        fake_prompts = {
            "entity_extraction_system_prompt": "You are an entity extractor."
        }
        with patch("lightrag.prompt.PROMPTS", fake_prompts):
            from rag.job_rag import JobRAG
            JobRAG._patch_extraction_prompt()
        return fake_prompts["entity_extraction_system_prompt"]

    # -- 现有规则保留 --

    def test_preserves_skills_normalization(self):
        prompt = self._get_patched_prompt()
        assert "技能（Skills）规范化" in prompt
        assert "React.js / ReactJS → React" in prompt

    def test_preserves_city_normalization(self):
        prompt = self._get_patched_prompt()
        assert "城市（City）规范化" in prompt
        assert "上海-浦东新区 → 上海" in prompt

    def test_preserves_company_rules(self):
        prompt = self._get_patched_prompt()
        assert "公司（Company）不合并规则" in prompt
        assert "某知名公司" in prompt

    # -- 新增规则 10-14 --

    def test_rule10_experience_normalization(self):
        prompt = self._get_patched_prompt()
        assert "经验年限规范化" in prompt
        assert "3-5年" in prompt
        assert "经验不限" in prompt

    def test_rule11_education_normalization(self):
        prompt = self._get_patched_prompt()
        assert "学历规范化" in prompt
        for keyword in ("本科", "硕士", "大专", "博士"):
            assert keyword in prompt

    def test_rule12_salary_normalization(self):
        prompt = self._get_patched_prompt()
        assert "薪资规范化" in prompt
        assert "40-70K" in prompt

    def test_rule13_job_type_normalization(self):
        prompt = self._get_patched_prompt()
        assert "岗位类型规范化" in prompt
        assert "AI Agent 工程师" in prompt
        assert "后端工程师" in prompt
        assert "算法工程师" in prompt

    def test_rule14_industry_normalization(self):
        prompt = self._get_patched_prompt()
        assert "行业规范化" in prompt
        assert "人工智能" in prompt
        assert "互联网" in prompt
        assert "金融科技" in prompt

    def test_idempotent_patch(self):
        """Calling _patch_extraction_prompt twice should not duplicate rules."""
        fake_prompts = {
            "entity_extraction_system_prompt": "You are an entity extractor."
        }
        with patch("lightrag.prompt.PROMPTS", fake_prompts):
            from rag.job_rag import JobRAG
            JobRAG._patch_extraction_prompt()
            first = fake_prompts["entity_extraction_system_prompt"]
            JobRAG._patch_extraction_prompt()
            second = fake_prompts["entity_extraction_system_prompt"]
        assert first == second


# ---------------------------------------------------------------------------
# 检索接口单元测试 (6.5)
# 需求: 4.1, 4.2, 4.4, 2.5
# ---------------------------------------------------------------------------

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class TestQueryForAgent:
    """query_for_agent 的 mode 参数透传和错误处理。"""

    def _make_rag(self):
        rag = MagicMock()
        rag._initialized = True
        rag._rag = MagicMock()
        rag._rag.aquery = AsyncMock(return_value="mock answer")
        rag._inserted_ids = set()
        # Bind the real methods
        from rag.job_rag import JobRAG
        rag.is_ready = True
        rag.query_for_agent = JobRAG.query_for_agent.__get__(rag, type(rag))
        return rag

    def test_mode_param_passed_to_query_param(self):
        """mode 参数应透传给 QueryParam。"""
        rag = self._make_rag()
        captured_params = []

        async def capture_aquery(query, param=None):
            captured_params.append(param)
            return "result"

        rag._rag.aquery = capture_aquery

        asyncio.run(rag.query_for_agent("test query", mode="local"))

        assert len(captured_params) == 1
        assert captured_params[0].mode == "local"

    def test_top_k_param_passed_to_query_param(self):
        """top_k 参数应透传给 QueryParam。"""
        rag = self._make_rag()
        captured_params = []

        async def capture_aquery(query, param=None):
            captured_params.append(param)
            return "result"

        rag._rag.aquery = capture_aquery

        asyncio.run(rag.query_for_agent("test query", top_k=5))

        assert len(captured_params) == 1
        assert captured_params[0].top_k == 5

    def test_default_mode_is_hybrid(self):
        """默认 mode 应为 hybrid。"""
        rag = self._make_rag()
        captured_params = []

        async def capture_aquery(query, param=None):
            captured_params.append(param)
            return "result"

        rag._rag.aquery = capture_aquery

        asyncio.run(rag.query_for_agent("test query"))

        assert captured_params[0].mode == "hybrid"

    def test_timeout_error_returns_specific_message(self):
        """TimeoutError 应返回 '检索超时' 消息。"""
        rag = self._make_rag()
        rag._rag.aquery = AsyncMock(side_effect=TimeoutError("timed out"))

        result = asyncio.run(rag.query_for_agent("test query"))

        assert "检索超时" in result

    def test_generic_error_includes_exception_type(self):
        """其他异常应返回包含异常类型名的消息。"""
        rag = self._make_rag()
        rag._rag.aquery = AsyncMock(side_effect=ValueError("bad value"))

        result = asyncio.run(rag.query_for_agent("test query"))

        assert "ValueError" in result
        assert "bad value" in result


class TestInsertJobIdempotent:
    """insert_job 的幂等行为。需求 2.5。"""

    def test_duplicate_insert_returns_true(self):
        """已插入的 job_id 再次插入应返回 True 且不调用 ainsert。"""
        from rag.job_rag import JobRAG

        rag = JobRAG.__new__(JobRAG)
        rag._initialized = True
        rag._rag = MagicMock()
        rag._rag.ainsert = AsyncMock()
        rag._inserted_ids = {42}  # Already inserted

        job = {"id": 42, "title": "Test Job", "raw_jd": "x" * 60}
        result = asyncio.run(rag.insert_job(job))

        assert result is True
        rag._rag.ainsert.assert_not_called()

    def test_new_insert_calls_ainsert(self):
        """新 job_id 应调用 ainsert 并加入 _inserted_ids。"""
        from rag.job_rag import JobRAG

        rag = JobRAG.__new__(JobRAG)
        rag._initialized = True
        rag._rag = MagicMock()
        rag._rag.ainsert = AsyncMock()
        rag._inserted_ids = set()

        job = {"id": 99, "title": "New Job", "raw_jd": "x" * 60}
        result = asyncio.run(rag.insert_job(job))

        assert result is True
        rag._rag.ainsert.assert_called_once()
        assert 99 in rag._inserted_ids

# ---------------------------------------------------------------------------
# RAGQueryTool 单元测试 (7.2)
# 需求: 6.1, 6.4, 6.5
# ---------------------------------------------------------------------------

import pytest
from unittest.mock import AsyncMock as _AsyncMock

from tools.data.rag_query import RAGQueryTool


class TestRAGQueryToolPrecision:
    """RAGQueryTool 增强功能测试：top_k 透传、query_time_ms、无效 mode。"""

    @pytest.fixture
    def tool(self):
        return RAGQueryTool()

    def _ready_rag(self, **overrides):
        rag = _AsyncMock()
        rag.is_ready = True
        rag.query_for_agent.return_value = "answer text"
        rag.query_entities.return_value = [{"id": 1, "title": "Job"}]
        for k, v in overrides.items():
            setattr(rag, k, v)
        return rag

    # -- top_k 透传 (需求 6.1) --

    @pytest.mark.asyncio
    async def test_answer_mode_passes_top_k(self, tool):
        """mode=answer 时 top_k 应透传给 query_for_agent。"""
        rag = self._ready_rag()
        await tool.execute(
            {"query": "test", "mode": "answer", "top_k": 10},
            {"job_rag": rag},
        )
        rag.query_for_agent.assert_awaited_once_with("test", top_k=10)

    @pytest.mark.asyncio
    async def test_search_mode_passes_top_k(self, tool):
        """mode=search 时 top_k 应透传给 query_entities。"""
        rag = self._ready_rag()
        await tool.execute(
            {"query": "test", "mode": "search", "top_k": 3},
            {"job_rag": rag},
        )
        rag.query_entities.assert_awaited_once_with("test", top_k=3)

    @pytest.mark.asyncio
    async def test_top_k_none_when_omitted(self, tool):
        """未提供 top_k 时应传 None。"""
        rag = self._ready_rag()
        await tool.execute(
            {"query": "test", "mode": "answer"},
            {"job_rag": rag},
        )
        rag.query_for_agent.assert_awaited_once_with("test", top_k=None)

    # -- query_time_ms 返回 (需求 6.4) --

    @pytest.mark.asyncio
    async def test_answer_mode_returns_query_time_ms(self, tool):
        """mode=answer 返回结果应包含 query_time_ms 且为非负整数。"""
        rag = self._ready_rag()
        result = await tool.execute(
            {"query": "test", "mode": "answer"},
            {"job_rag": rag},
        )
        assert "query_time_ms" in result
        assert isinstance(result["query_time_ms"], int)
        assert result["query_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_search_mode_returns_query_time_ms(self, tool):
        """mode=search 返回结果应包含 query_time_ms 且为非负整数。"""
        rag = self._ready_rag()
        result = await tool.execute(
            {"query": "test", "mode": "search"},
            {"job_rag": rag},
        )
        assert "query_time_ms" in result
        assert isinstance(result["query_time_ms"], int)
        assert result["query_time_ms"] >= 0

    # -- 无效 mode 错误信息 (需求 6.5) --

    @pytest.mark.asyncio
    async def test_invalid_mode_lists_valid_values(self, tool):
        """无效 mode 应返回包含 'answer' 和 'search' 的错误信息。"""
        rag = self._ready_rag()
        result = await tool.execute(
            {"query": "test", "mode": "bad"},
            {"job_rag": rag},
        )
        assert result["success"] is False
        assert "answer" in result["error"]
        assert "search" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_mode_returns_error(self, tool):
        """空 mode 应返回错误。"""
        rag = self._ready_rag()
        result = await tool.execute(
            {"query": "test", "mode": ""},
            {"job_rag": rag},
        )
        assert result["success"] is False
        assert "有效值" in result["error"]
