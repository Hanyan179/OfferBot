"""Embedding 工具函数 — 使用 OpenAI 兼容 API。"""

from __future__ import annotations

import numpy as np
from openai import AsyncOpenAI


async def get_embeddings(
    texts: list[str],
    api_key: str,
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: str = "text-embedding-v3",
) -> np.ndarray:
    """批量获取文本 embedding。"""
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    # 截断过长文本
    truncated = [t[:8000] for t in texts]
    resp = await client.embeddings.create(input=truncated, model=model)
    vectors = [item.embedding for item in resp.data]
    return np.array(vectors, dtype=np.float32)
