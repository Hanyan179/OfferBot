"""
岗位向量索引 — 基于 FAISS 的岗位语义检索

职责：
1. 将岗位 JD 向量化并建立 FAISS 索引
2. 提供语义检索接口，返回匹配的岗位实体
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

INDEX_DIR = Path(__file__).resolve().parent.parent / "data" / "job_index"

class JobVectorIndex:
    """岗位向量索引管理器。"""

    def __init__(self, index_dir: str | None = None) -> None:
        self._dir = Path(index_dir) if index_dir else INDEX_DIR
        self._index = None  # FAISS index
        self._id_map: list[int] = []  # position → job_id
        self._loaded = False

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _index_path(self) -> Path:
        return self._dir / "jobs.faiss"

    def _map_path(self) -> Path:
        return self._dir / "id_map.json"

    def load(self) -> bool:
        """加载已有索引，返回是否成功。"""
        if self._loaded:
            return True
        if not self._index_path().exists():
            return False
        try:
            import faiss
            self._index = faiss.read_index(str(self._index_path()))
            self._id_map = json.loads(self._map_path().read_text())
            self._loaded = True
            logger.info("加载岗位索引: %d 条", self._index.ntotal)
            return True
        except Exception as e:
            logger.error("加载索引失败: %s", e)
            return False

    def save(self) -> None:
        """保存索引到磁盘。"""
        if self._index is None:
            return
        import faiss
        self._ensure_dir()
        faiss.write_index(self._index, str(self._index_path()))
        self._map_path().write_text(json.dumps(self._id_map))
        logger.info("保存岗位索引: %d 条", self._index.ntotal)

    async def build_from_db(self, db: Any, embed_fn) -> int:
        """从数据库构建索引（有 JD 的岗位）。

        Args:
            db: Database 实例
            embed_fn: async (texts: list[str]) -> np.ndarray  embedding 函数

        Returns:
            索引的岗位数量
        """
        rows = await db.execute(
            "SELECT id, title, company, raw_jd FROM jobs WHERE raw_jd IS NOT NULL AND raw_jd != ''"
        )
        if not rows:
            return 0

        texts = [f"{r['title']} {r['company']} {r['raw_jd']}" for r in rows]
        ids = [r["id"] for r in rows]

        embeddings = await embed_fn(texts)
        dim = embeddings.shape[1]

        import faiss
        self._index = faiss.IndexFlatIP(dim)  # 内积相似度
        # L2 归一化后内积 = 余弦相似度
        faiss.normalize_L2(embeddings)
        self._index.add(embeddings)
        self._id_map = ids
        self._loaded = True

        self.save()
        return len(ids)

    async def add_jobs(self, jobs: list[dict], embed_fn) -> int:
        """增量添加岗位到索引。

        Args:
            jobs: [{"id": int, "title": str, "company": str, "raw_jd": str}]
            embed_fn: embedding 函数
        """
        if not jobs:
            return 0

        if not self._loaded:
            self.load()

        texts = [f"{j['title']} {j['company']} {j['raw_jd']}" for j in jobs]
        embeddings = await embed_fn(texts)

        import faiss
        faiss.normalize_L2(embeddings)

        if self._index is None:
            dim = embeddings.shape[1]
            self._index = faiss.IndexFlatIP(dim)

        # 去重：已在索引中的 id 跳过
        existing = set(self._id_map)
        new_mask = [i for i, j in enumerate(jobs) if j["id"] not in existing]
        if not new_mask:
            return 0

        new_embeddings = embeddings[new_mask]
        self._index.add(new_embeddings)
        for i in new_mask:
            self._id_map.append(jobs[i]["id"])

        self.save()
        return len(new_mask)

    async def search(self, query: str, embed_fn, top_k: int = 10) -> list[dict]:
        """语义检索，返回 [{job_id, score}]。"""
        if not self._loaded:
            if not self.load():
                return []

        if self._index is None or self._index.ntotal == 0:
            return []

        q_emb = await embed_fn([query])
        import faiss
        faiss.normalize_L2(q_emb)

        k = min(top_k, self._index.ntotal)
        scores, indices = self._index.search(q_emb, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._id_map):
                continue
            results.append({"job_id": self._id_map[idx], "score": float(score)})
        return results

    @property
    def count(self) -> int:
        if self._index is None:
            return 0
        return self._index.ntotal
