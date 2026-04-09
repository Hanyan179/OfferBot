"""岗位知识图谱 + 向量检索管理器 — 封装 LightRAG 实例。"""
from __future__ import annotations
import asyncio, json, logging, os, re, time
from typing import Any

logger = logging.getLogger(__name__)

def _safe_parse_json_list(value) -> list[str]:
    if value is None: return []
    if isinstance(value, list): return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list): return [str(v) for v in parsed]
        except (json.JSONDecodeError, TypeError): pass
    return []

def _extract_job_ids(text: str, job_ids: list[int]) -> None:
    for m in re.finditer(r"【岗位ID】(\d+)", text):
        jid = int(m.group(1))
        if jid not in job_ids: job_ids.append(jid)

_INVALID_JD_PATTERNS = {"暂无", "无", "待补充", "暂无描述", "无描述"}

class JobRAG:
    _EMBEDDING_PRESETS = {
        "dashscope": {"model": "text-embedding-v3", "dim": 1024, "max_input": 8000},
        "gemini": {"model": "gemini-embedding-001", "dim": 3072, "max_input": 2048, "no_dim": True},
        "openai": {"model": "text-embedding-3-small", "dim": 1536, "max_input": 8000},
        "deepseek": {"model": "text-embedding-v3", "dim": 1024, "max_input": 8000},
    }

    def __init__(self, working_dir: str, api_key: str, base_url: str, model: str, db: Any | None = None):
        self._working_dir = working_dir
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._db = db
        self._rag = None
        self._initialized = False
        self._inserted_ids: set = set()

    @classmethod
    def _detect_provider(cls, base_url: str) -> str:
        u = (base_url or "").lower()
        if "generativelanguage.googleapis" in u or "gemini" in u: return "gemini"
        if "dashscope" in u: return "dashscope"
        if "deepseek" in u: return "deepseek"
        if "openai" in u: return "openai"
        return "dashscope"

    async def initialize(self) -> None:
        try:
            import numpy as np
            from lightrag import LightRAG
            from lightrag.llm.openai import openai_complete_if_cache
            from lightrag.utils import EmbeddingFunc
            from openai import AsyncOpenAI
            api_key, base_url, model = self._api_key, self._base_url, self._model
            provider = self._detect_provider(base_url)
            ec = self._EMBEDDING_PRESETS.get(provider, self._EMBEDDING_PRESETS["dashscope"])
            e_model, e_dim, e_max = ec["model"], ec["dim"], ec["max_input"]
            no_dim = ec.get("no_dim", False)
            logger.info("JobRAG provider=%s LLM=%s embed=%s(%d)", provider, model, e_model, e_dim)
            async def _llm(prompt, system_prompt=None, history_messages=[], **kw):
                return await openai_complete_if_cache(model, prompt, system_prompt=system_prompt,
                    history_messages=history_messages, api_key=api_key, base_url=base_url, **kw)
            _ec = AsyncOpenAI(api_key=api_key, base_url=base_url)
            async def _embed(texts: list[str]) -> np.ndarray:
                kw: dict = {"model": e_model, "input": [t[:e_max] for t in texts]}
                if not no_dim: kw["dimensions"] = e_dim
                r = await _ec.embeddings.create(**kw)
                return np.array([e.embedding for e in r.data], dtype=np.float32)
            self._rag = LightRAG(working_dir=self._working_dir, llm_model_func=_llm,
                embedding_func=EmbeddingFunc(embedding_dim=e_dim, max_token_size=8192, func=_embed),
                addon_params={"entity_types": ["岗位","公司","技能","城市","薪资","职责","任职要求","行业"], "language": "Chinese"})
            self._patch_extraction_prompt()
            await self._rag.initialize_storages()
            self._initialized = True
            logger.info("JobRAG 初始化成功: %s (provider=%s)", self._working_dir, provider)
        except Exception as e:
            logger.error("JobRAG 初始化失败: %s", e)
            self._initialized = False

    @staticmethod
    def _patch_extraction_prompt() -> None:
        from lightrag.prompt import PROMPTS
        rules = """

9.  **Entity Normalization Rules (Domain: Job Recruitment):**
    *   **技能（Skills）规范化 — 必须严格执行：**
        -   React.js / ReactJS → React；Vue.js / VueJS → Vue；Node.js / NodeJS → Node.js
        -   TypeScript / TS → TypeScript；JavaScript / JS → JavaScript
        -   LangChain / langchain → LangChain；PyTorch / pytorch → PyTorch
        -   TensorFlow / tensorflow → TensorFlow；C++ / CPP → C++
        -   "Python/C++" 拆分为 Python 和 C++
        -   Python3 → Python；Java8 → Java；ES6 → JavaScript
        -   NLP / 自然语言处理 → NLP；CV / 计算机视觉 → 计算机视觉
        -   ML / 机器学习 → 机器学习；DL / 深度学习 → 深度学习；RL / 强化学习 → 强化学习
        -   包含关系（RAG 和 多模态RAG）保留各自独立
    *   **城市（City）规范化：** 上海-浦东新区 → 上海；北京-海淀区 → 北京；深圳-南山区 → 深圳
    *   **公司（Company）不合并规则：** "某知名公司" 等脱敏名称不得合并
10. **经验年限规范化：** "3-5年经验" → "3-5年"；"不限经验" → "经验不限"
11. **学历规范化：** "本科及以上" → "本科"；"硕士及以上" → "硕士"；"大专及以上" → "大专"
12. **薪资规范化：** "40-70K"、"40K-70K/月" → "40-70K"
13. **岗位类型规范化：** "AI Agent 工程师/研发/开发" → "AI Agent 工程师"；"后端开发/工程师" → "后端工程师"
14. **行业规范化：** "人工智能/AI" → "人工智能"；"互联网/移动互联网" → "互联网"；"金融/Fintech" → "金融科技"
"""
        orig = PROMPTS["entity_extraction_system_prompt"]
        if "Entity Normalization Rules" not in orig:
            PROMPTS["entity_extraction_system_prompt"] = orig.rstrip() + rules

    @staticmethod
    def _build_document(job: dict) -> str:
        s_min, s_max = job.get("salary_min",""), job.get("salary_max","")
        salary = f"{s_min}-{s_max}K" if s_min and s_max else ""
        parts = [f"【岗位ID】{job.get('id','')}",f"【岗位】{job.get('title','')}",
                 f"【公司】{job.get('company','')}",f"【城市】{job.get('city','')}",
                 f"【薪资】{salary}",f"【链接】{job.get('url','')}"]
        for field, label in [("skills_must","必备技能"),("skills_preferred","优先技能")]:
            v = _safe_parse_json_list(job.get(field))
            if v: parts.append(f"【{label}】{', '.join(v)}")
        resp = _safe_parse_json_list(job.get("responsibilities"))
        if resp: parts.append("【岗位职责】\n" + "\n".join(f"- {r}" for r in resp))
        e_min, e_max = job.get("experience_min"), job.get("experience_max")
        if e_min is not None or e_max is not None:
            parts.append(f"【经验要求】{e_min or 0}-{e_max or '不限'}年")
        if job.get("education"): parts.append(f"【学历要求】{job['education']}")
        if job.get("company_industry"): parts.append(f"【行业】{job['company_industry']}")
        raw_jd = job.get("raw_jd", "")
        if len(raw_jd) > 4000: raw_jd = raw_jd[:4000] + "...（已截断）"
        parts.append(f"【职位描述】{raw_jd}")
        return "\n".join(parts)

    def _validate_job(self, job: dict) -> tuple[bool, str]:
        if not job.get("id"): return False, "缺少 id"
        title = job.get("title", "")
        if not title or not title.strip(): return False, "缺少 title"
        raw_jd = job.get("raw_jd", "")
        if not raw_jd or not raw_jd.strip(): return False, "缺少 raw_jd"
        if raw_jd.strip() in _INVALID_JD_PATTERNS: return False, f"raw_jd 为占位文本: {raw_jd.strip()}"
        if len(raw_jd.strip()) < 50: return False, f"raw_jd 过短: {len(raw_jd.strip())} 字符"
        return True, ""

    async def insert_job(self, job: dict) -> bool:
        if not self.is_ready: return False
        ok, reason = self._validate_job(job)
        if not ok:
            logger.warning("跳过插入 (id=%s): %s", job.get("id"), reason); return False
        jid = job.get("id")
        if jid in self._inserted_ids: return True
        try:
            await self._rag.ainsert(self._build_document(job))
            self._inserted_ids.add(jid); return True
        except Exception as e:
            logger.warning("插入失败 (id=%s): %s", jid, e); return False

    async def insert_jobs_batch(self, jobs: list[dict]) -> tuple[int, int]:
        if not self.is_ready: return 0, 0
        valid, skip = [], 0
        for j in jobs:
            ok, r = self._validate_job(j)
            if ok: valid.append(j)
            else: skip += 1; logger.warning("跳过 (id=%s): %s", j.get("id"), r)
        logger.info("批量插入: 总 %d, 通过 %d, 跳过 %d", len(jobs), len(valid), skip)
        sem, success, fail = asyncio.Semaphore(3), 0, 0
        t0 = time.time()
        async def _one(j):
            nonlocal success, fail
            async with sem:
                try:
                    await self._rag.ainsert(self._build_document(j))
                    self._inserted_ids.add(j.get("id")); success += 1
                except Exception as e: fail += 1; logger.warning("插入失败 (id=%s): %s", j.get("id"), e)
        await asyncio.gather(*[_one(j) for j in valid])
        logger.info("批量完成: 成功 %d, 失败 %d, %.1fs", success, fail, time.time()-t0)
        if (success+fail) > 0 and fail/(success+fail) > 0.5:
            logger.error("失败率 >50%%")
        return success, fail + skip

    async def query_for_agent(self, query: str, *, top_k: int|None=None, mode: str="hybrid") -> str:
        if not self.is_ready: return "知识图谱未初始化，需要先抓取岗位详情"
        try:
            from lightrag import QueryParam
            t0 = time.time()
            p = QueryParam(mode=mode)
            if top_k is not None: p.top_k = top_k
            r = await self._rag.aquery(query, param=p)
            logger.debug("query_for_agent: %.0fms", (time.time()-t0)*1000)
            return str(r)
        except TimeoutError: return "检索超时，请稍后重试"
        except Exception as e:
            logger.error("query_for_agent 失败: %s", e)
            return f"检索失败: {type(e).__name__}: {e}"

    async def query_entities(self, query: str, *, top_k: int|None=None) -> list[dict]:
        if not self.is_ready: return []
        try:
            from lightrag import QueryParam
            p = QueryParam(mode="hybrid")
            if top_k is not None: p.top_k = top_k
            data = await self._rag.aquery_data(query, param=p)
            if data.get("status") != "success": return []
            ids: list[int] = []
            inner = data.get("data", {})
            for c in inner.get("chunks", []): _extract_job_ids(c.get("content",""), ids)
            for e in inner.get("entities", []):
                for f in ("description","source_id"): _extract_job_ids(e.get(f,""), ids)
            for r in inner.get("relationships", []):
                for f in ("description","source_id"): _extract_job_ids(r.get(f,""), ids)
            if not ids or not self._db: return []
            ph = ",".join("?"*len(ids))
            rows = await self._db.execute(f"SELECT id,title,company,salary_min,salary_max,url FROM jobs WHERE id IN ({ph})", tuple(ids))
            rm = {r["id"]: dict(r) for r in rows}
            out = []
            for i in ids:
                if i in rm: out.append(rm[i])
                else: logger.warning("岗位 ID %d 不存在", i)
            return out
        except Exception as e:
            logger.error("query_entities 失败: %s", e); return []

    async def finalize(self) -> None:
        if self._rag:
            try: await self._rag.finalize_storages()
            except Exception as e: logger.warning("finalize 失败: %s", e)
            self._rag = None; self._initialized = False

    @property
    def is_ready(self) -> bool:
        return self._initialized and self._rag is not None

    async def rebuild(self) -> None:
        import shutil
        logger.info("开始重建图谱: %s", self._working_dir)
        await self.finalize()
        if os.path.exists(self._working_dir): shutil.rmtree(self._working_dir)
        os.makedirs(self._working_dir, exist_ok=True)
        self._inserted_ids.clear()
        await self.initialize()
        if not self._db:
            logger.error("rebuild: 无数据库"); self._initialized = False; return
        rows = await self._db.execute(
            "SELECT id,title,company,city,salary_min,salary_max,url,raw_jd,"
            "skills_must,skills_preferred,responsibilities,experience_min,"
            "experience_max,education,company_industry "
            "FROM jobs WHERE raw_jd IS NOT NULL AND raw_jd != ''")
        jobs = [dict(r) for r in rows]
        logger.info("待重建: %d 条", len(jobs))
        s, f = await self.insert_jobs_batch(jobs)
        logger.info("重建完成: 成功 %d, 失败 %d", s, f)

    def get_graph_stats(self) -> dict:
        import networkx as nx; from collections import Counter
        p = os.path.join(self._working_dir, "graph_chunk_entity_relation.graphml")
        if not os.path.exists(p): return {"error": "graphml 不存在"}
        G = nx.read_graphml(p)
        types = Counter(d.get("entity_type","unknown") for _,d in G.nodes(data=True))
        return {"total_entities": G.number_of_nodes(), "total_relations": G.number_of_edges(),
                "entity_types": dict(types), "isolated_entities": sum(1 for n in G.nodes() if G.degree(n)==0)}

    def get_entities_by_type(self, entity_type: str) -> list[str]:
        import networkx as nx
        p = os.path.join(self._working_dir, "graph_chunk_entity_relation.graphml")
        if not os.path.exists(p): return []
        G = nx.read_graphml(p)
        return [n for n,d in G.nodes(data=True) if d.get("entity_type")==entity_type]

    def get_relations_for_entity(self, entity_name: str) -> list[dict]:
        import networkx as nx
        p = os.path.join(self._working_dir, "graph_chunk_entity_relation.graphml")
        if not os.path.exists(p): return []
        G = nx.read_graphml(p)
        if entity_name not in G: return []
        rels = [{"source":u,"target":v,**d} for u,v,d in G.edges(entity_name, data=True)]
        rels += [{"source":u,"target":v,**d} for u,v,d in G.edges(data=True) if v==entity_name and u!=entity_name]
        return rels

    def get_vector_stats(self) -> dict:
        stats = {}
        for n in ("vdb_chunks","vdb_entities","vdb_relationships"):
            p = os.path.join(self._working_dir, f"{n}.json")
            if os.path.exists(p):
                with open(p) as f: stats[n] = {"count": len(json.load(f))}
            else: stats[n] = {"count": 0, "missing": True}
        return stats
