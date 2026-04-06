"""知识图谱检索 — 基于 LightRAG 的混合检索工具。"""

from __future__ import annotations

from typing import Any

from agent.tool_registry import Tool


class RAGQueryTool(Tool):
    """基于岗位知识图谱和向量检索回答问题。"""

    @property
    def name(self) -> str:
        return "rag_query"

    @property
    def display_name(self) -> str:
        return "知识检索"

    @property
    def description(self) -> str:
        return (
            "基于岗位知识图谱和向量检索回答问题。"
            "mode='answer': 需要 AI 分析回答的问题（画像匹配推荐、匹配度分析、知识问答）。"
            "mode='search': 查找相似岗位，返回精简列表。"
        )

    @property
    def category(self) -> str:
        return "data"

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户问题或搜索描述",
                },
                "mode": {
                    "type": "string",
                    "enum": ["answer", "search"],
                    "description": (
                        "answer=AI 分析回答（画像匹配、匹配度分析、知识问答），"
                        "search=查找相似岗位返回列表"
                    ),
                },
            },
            "required": ["query", "mode"],
        }

    async def execute(self, params: dict, context: Any) -> dict:
        job_rag = context.get("job_rag") if isinstance(context, dict) else None

        if not job_rag or not job_rag.is_ready:
            return {
                "success": False,
                "error": "知识图谱未初始化，需要先抓取岗位详情",
            }

        query = params.get("query", "")
        mode = params.get("mode", "")

        if mode == "answer":
            text = await job_rag.query_for_agent(query)
            return {"success": True, "answer": text, "for_agent": True}

        if mode == "search":
            entities = await job_rag.query_entities(query)
            return {
                "success": True,
                "count": len(entities),
                "jobs": entities,
                "for_agent": False,
            }

        return {"success": False, "error": f"未知 mode: {mode}"}
