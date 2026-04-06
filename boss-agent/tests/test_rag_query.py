"""RAGQueryTool 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from tools.data.rag_query import RAGQueryTool


@pytest.fixture
def tool():
    return RAGQueryTool()


# ── Meta ──────────────────────────────────────────────────────────────

class TestRAGQueryToolMeta:
    def test_name(self, tool: RAGQueryTool):
        assert tool.name == "rag_query"

    def test_display_name(self, tool: RAGQueryTool):
        assert tool.display_name == "知识检索"

    def test_category(self, tool: RAGQueryTool):
        assert tool.category == "data"

    def test_concurrency_safe(self, tool: RAGQueryTool):
        assert tool.is_concurrency_safe is True

    def test_schema_has_query_and_mode(self, tool: RAGQueryTool):
        schema = tool.parameters_schema
        assert "query" in schema["properties"]
        assert "mode" in schema["properties"]
        assert schema["properties"]["mode"]["enum"] == ["answer", "search"]
        assert schema["required"] == ["query", "mode"]


# ── Execute ───────────────────────────────────────────────────────────

class TestRAGQueryExecute:
    @pytest.mark.asyncio
    async def test_no_job_rag_returns_error(self, tool: RAGQueryTool):
        """context 中没有 job_rag 时返回错误。"""
        result = await tool.execute({"query": "test", "mode": "answer"}, {})
        assert result["success"] is False
        assert "未初始化" in result["error"]

    @pytest.mark.asyncio
    async def test_job_rag_not_ready_returns_error(self, tool: RAGQueryTool):
        """job_rag.is_ready 为 False 时返回错误。"""
        mock_rag = AsyncMock()
        mock_rag.is_ready = False
        result = await tool.execute(
            {"query": "test", "mode": "answer"},
            {"job_rag": mock_rag},
        )
        assert result["success"] is False
        assert "未初始化" in result["error"]

    @pytest.mark.asyncio
    async def test_answer_mode_calls_query_for_agent(self, tool: RAGQueryTool):
        """mode=answer 调用 query_for_agent 并返回正确格式。"""
        mock_rag = AsyncMock()
        mock_rag.is_ready = True
        mock_rag.query_for_agent.return_value = "这是分析结果"

        result = await tool.execute(
            {"query": "适合我的岗位", "mode": "answer"},
            {"job_rag": mock_rag},
        )

        mock_rag.query_for_agent.assert_awaited_once_with("适合我的岗位")
        assert result == {
            "success": True,
            "answer": "这是分析结果",
            "for_agent": True,
        }

    @pytest.mark.asyncio
    async def test_search_mode_calls_query_entities(self, tool: RAGQueryTool):
        """mode=search 调用 query_entities 并返回正确格式。"""
        fake_jobs = [
            {"id": 1, "title": "AI 工程师", "company": "京东", "salary_min": 30, "salary_max": 50, "url": "https://example.com/1"},
            {"id": 2, "title": "后端开发", "company": "字节", "salary_min": 25, "salary_max": 45, "url": "https://example.com/2"},
        ]
        mock_rag = AsyncMock()
        mock_rag.is_ready = True
        mock_rag.query_entities.return_value = fake_jobs

        result = await tool.execute(
            {"query": "类似的岗位", "mode": "search"},
            {"job_rag": mock_rag},
        )

        mock_rag.query_entities.assert_awaited_once_with("类似的岗位")
        assert result["success"] is True
        assert result["count"] == 2
        assert result["jobs"] == fake_jobs
        assert result["for_agent"] is False

    @pytest.mark.asyncio
    async def test_search_mode_empty_results(self, tool: RAGQueryTool):
        """mode=search 无结果时返回空列表。"""
        mock_rag = AsyncMock()
        mock_rag.is_ready = True
        mock_rag.query_entities.return_value = []

        result = await tool.execute(
            {"query": "不存在的岗位", "mode": "search"},
            {"job_rag": mock_rag},
        )

        assert result["success"] is True
        assert result["count"] == 0
        assert result["jobs"] == []

    @pytest.mark.asyncio
    async def test_unknown_mode_returns_error(self, tool: RAGQueryTool):
        """未知 mode 返回错误。"""
        mock_rag = AsyncMock()
        mock_rag.is_ready = True

        result = await tool.execute(
            {"query": "test", "mode": "invalid"},
            {"job_rag": mock_rag},
        )

        assert result["success"] is False
        assert "未知 mode" in result["error"]

    @pytest.mark.asyncio
    async def test_context_not_dict_returns_error(self, tool: RAGQueryTool):
        """context 不是 dict 时返回错误。"""
        result = await tool.execute({"query": "test", "mode": "answer"}, None)
        assert result["success"] is False
