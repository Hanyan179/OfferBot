"""
岗位知识图谱 + 向量检索管理器 — 封装 LightRAG 实例

职责：
1. 管理 LightRAG 实例的生命周期（初始化、释放）
2. 将岗位 JD 数据插入知识图谱
3. 提供两种检索接口：
   - query_for_agent: 返回文本回答供 Agent 消费（S1/S4/S5/S7-S11 场景）
   - query_entities: 返回精简岗位列表（S3 场景）
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class JobRAG:
    """岗位知识图谱 + 向量检索管理器，封装 LightRAG 实例。"""

    def __init__(
        self,
        working_dir: str,
        api_key: str,
        base_url: str,
        model: str,
        db: Any | None = None,
    ) -> None:
        self._working_dir = working_dir
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._db = db
        self._rag = None
        self._initialized = False

    async def initialize(self) -> None:
        """初始化 LightRAG 实例和存储。

        配置：
        - LLM: OpenAI 兼容格式（通过 base_url + model）
        - Embedding: 本地 bge-small-zh-v1.5（95MB，无需 API）
        - entity_types: 中文招聘场景实体
        - language: Chinese
        """
        try:
            import numpy as np
            from lightrag import LightRAG
            from lightrag.llm.openai import openai_complete_if_cache
            from lightrag.utils import EmbeddingFunc
            from sentence_transformers import SentenceTransformer

            api_key = self._api_key
            base_url = self._base_url
            model = self._model

            # LLM 包装：openai_complete_if_cache 需要 model 作为第一个位置参数
            async def _llm_func(
                prompt, system_prompt=None, history_messages=[], **kwargs
            ):
                return await openai_complete_if_cache(
                    model, prompt,
                    system_prompt=system_prompt,
                    history_messages=history_messages,
                    api_key=api_key, base_url=base_url,
                    **kwargs,
                )

            # Embedding：本地模型，无需 API
            _embed_model = SentenceTransformer("BAAI/bge-small-zh-v1.5")

            async def _local_embed(texts: list[str]) -> np.ndarray:
                import asyncio
                return await asyncio.to_thread(
                    _embed_model.encode, texts, normalize_embeddings=True
                )

            self._rag = LightRAG(
                working_dir=self._working_dir,
                llm_model_func=_llm_func,
                embedding_func=EmbeddingFunc(
                    embedding_dim=512,
                    max_token_size=8192,
                    func=_local_embed,
                ),
                addon_params={
                    "entity_types": [
                        "岗位", "公司", "技能", "城市",
                        "薪资", "职责", "任职要求", "行业",
                    ],
                    "language": "Chinese",
                },
            )

            # 注入实体规范化规则到抽取 prompt
            self._patch_extraction_prompt()

            await self._rag.initialize_storages()
            self._initialized = True
            logger.info("JobRAG 初始化成功: %s", self._working_dir)
        except Exception as e:
            logger.error("JobRAG 初始化失败: %s", e)
            self._initialized = False

    @staticmethod
    @staticmethod
    def _patch_extraction_prompt() -> None:
        """在 LightRAG 的实体抽取 prompt 末尾追加招聘领域的规范化规则。

        解决问题：
        - 技能近义词（React / React.js / ReactJS → React）
        - 城市层级（上海-浦东新区 → 上海）
        - 脱敏公司名不合并（"某知名公司"各自独立，因为是不同公司）
        """
        from lightrag.prompt import PROMPTS

        normalization_rules = """

9.  **Entity Normalization Rules (Domain: Job Recruitment):**
    *   **技能（Skills）规范化 — 必须严格执行：**
        -   同一技术的不同写法必须统一为最常用的简称：
            React.js / ReactJS → React；Vue.js / VueJS → Vue；Node.js / NodeJS → Node.js；
            TypeScript / TS → TypeScript；JavaScript / JS → JavaScript；
            LangChain / langchain → LangChain；PyTorch / pytorch → PyTorch；
            TensorFlow / tensorflow → TensorFlow；C++ / CPP → C++
        -   "Python/C++" 这种组合技能必须拆分为两个独立实体：Python 和 C++
        -   带版本号的统一去掉版本：Python3 → Python；Java8 → Java；ES6 → JavaScript
        -   缩写和全称统一为业界常用形式：NLP / 自然语言处理 → NLP；CV / 计算机视觉 → 计算机视觉；
            ML / 机器学习 → 机器学习；DL / 深度学习 → 深度学习；RL / 强化学习 → 强化学习
        -   如果两个技能是包含关系（如 RAG 和 多模态RAG），保留各自独立，不合并
    *   **城市（City）规范化：**
        -   统一到城市级别，去掉区县：上海-浦东新区 → 上海；北京-海淀区 → 北京；深圳-南山区 → 深圳
    *   **公司（Company）不合并规则：**
        -   "某知名公司"、"某上海知名公司"、"某基金公司" 等脱敏名称，即使语义相似也不得合并，因为它们代表不同的实际公司
        -   只有完全相同的公司名才视为同一实体
"""
        original = PROMPTS["entity_extraction_system_prompt"]
        if "Entity Normalization Rules" not in original:
            PROMPTS["entity_extraction_system_prompt"] = original.rstrip() + normalization_rules

    def _build_document(job: dict) -> str:
        """将岗位数据构建为结构化文档格式。"""
        salary_min = job.get("salary_min", "")
        salary_max = job.get("salary_max", "")
        salary = f"{salary_min}-{salary_max}K" if salary_min and salary_max else ""
        return (
            f"【岗位ID】{job.get('id', '')}\n"
            f"【岗位】{job.get('title', '')}\n"
            f"【公司】{job.get('company', '')}\n"
            f"【城市】{job.get('city', '')}\n"
            f"【薪资】{salary}\n"
            f"【链接】{job.get('url', '')}\n"
            f"【职位描述】{job.get('raw_jd', '')}"
        )

    async def insert_job(self, job: dict) -> bool:
        """插入单个岗位到知识图谱。"""
        if not self.is_ready:
            logger.warning("JobRAG 未就绪，跳过插入")
            return False
        try:
            doc = self._build_document(job)
            await self._rag.ainsert(doc)
            return True
        except Exception as e:
            logger.warning("插入岗位失败 (id=%s): %s", job.get("id"), e)
            return False

    async def insert_jobs_batch(self, jobs: list[dict]) -> int:
        """批量插入岗位，返回成功插入的数量。"""
        if not self.is_ready:
            logger.warning("JobRAG 未就绪，跳过批量插入")
            return 0
        docs = [self._build_document(j) for j in jobs]
        count = 0
        for doc in docs:
            try:
                await self._rag.ainsert(doc)
                count += 1
            except Exception as e:
                logger.warning("批量插入单条失败: %s", e)
        return count

    async def query_for_agent(self, query: str) -> str:
        """混合检索，返回文本回答供 Agent 消费。

        用于 S1/S4/S5/S7/S8/S9/S10/S11 场景。
        调用 LightRAG.aquery(mode="hybrid")。
        """
        if not self.is_ready:
            return "知识图谱未初始化，需要先抓取岗位详情"
        try:
            from lightrag import QueryParam

            result = await self._rag.aquery(
                query, param=QueryParam(mode="hybrid")
            )
            return str(result)
        except Exception as e:
            logger.error("query_for_agent 失败: %s", e)
            return f"检索失败: {e}"

    async def query_entities(self, query: str) -> list[dict]:
        """混合检索，返回精简岗位列表。

        用于 S3 场景。调用 LightRAG.aquery_data(mode="hybrid")，
        从返回的 chunks 和实体中提取岗位 ID，再从 SQLite 查完整信息。
        """
        if not self.is_ready:
            return []
        try:
            from lightrag import QueryParam

            data = await self._rag.aquery_data(
                query, param=QueryParam(mode="hybrid")
            )
            if data.get("status") != "success":
                return []

            job_ids: list[int] = []
            inner = data.get("data", {})

            # 优先从 chunks 提取（chunks 包含原始文档，有【岗位ID】字段）
            for chunk in inner.get("chunks", []):
                content = chunk.get("content", "")
                for m in re.finditer(r"【岗位ID】(\d+)", content):
                    jid = int(m.group(1))
                    if jid not in job_ids:
                        job_ids.append(jid)

            # 兜底：从实体描述和 source_id 提取
            for ent in inner.get("entities", []):
                for field in ("description", "source_id"):
                    text = ent.get(field, "")
                    for m in re.finditer(r"【岗位ID】(\d+)", text):
                        jid = int(m.group(1))
                        if jid not in job_ids:
                            job_ids.append(jid)

            if not job_ids or not self._db:
                return []

            ph = ",".join("?" * len(job_ids))
            rows = await self._db.execute(
                f"SELECT id, title, company, salary_min, salary_max, url "
                f"FROM jobs WHERE id IN ({ph})",
                tuple(job_ids),
            )
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("query_entities 失败: %s", e)
            return []

    async def finalize(self) -> None:
        """释放 LightRAG 存储资源。"""
        if self._rag is not None:
            try:
                await self._rag.finalize_storages()
            except Exception as e:
                logger.warning("finalize 失败: %s", e)
            self._rag = None
            self._initialized = False

    @property
    def is_ready(self) -> bool:
        """是否已初始化且可用。"""
        return self._initialized and self._rag is not None
