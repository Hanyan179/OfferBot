"""
LLM 客户端 — 统一使用 OpenAI 兼容格式

支持 DashScope（通义千问）、OpenAI、以及任何兼容 OpenAI API 的服务。
通过 api_base_url 切换后端，零代码改动。
"""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI 兼容格式的 LLM 客户端。"""

    def __init__(
        self,
        api_key: str,
        model: str = "qwen-plus",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ):
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    @property
    def model(self) -> str:
        return self._model

    async def chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """
        发送 chat completion 请求，返回 assistant 消息文本。

        Args:
            messages: OpenAI 格式的消息列表
            **kwargs: 透传给 openai client（temperature, max_tokens 等）

        Returns:
            LLM 响应文本
        """
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ):
        """
        发送 chat completion 请求（支持 function calling）。

        返回原始的 ChatCompletionMessage 对象，调用方自行处理
        text content 和 tool_calls。

        Args:
            messages: OpenAI 格式的消息列表
            tools: OpenAI function calling 格式的工具定义列表
            **kwargs: 透传给 openai client

        Returns:
            openai ChatCompletionMessage 对象
        """
        params: dict[str, Any] = {"model": self._model, "messages": messages, **kwargs}
        if tools:
            params["tools"] = tools

        response = await self._client.chat.completions.create(**params)
        return response.choices[0].message
