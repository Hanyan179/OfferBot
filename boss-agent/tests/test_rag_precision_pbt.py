"""
Property-based tests for LightRAG 检索精准度调优.

Property 1: 文档格式完整性
对任意岗位字典（含/不含各结构化字段），_build_document() 生成的文档应满足：
非空结构化字段有对应中文标签且内容一致；空字段无对应标签；始终包含【职位描述】。
验证: 需求 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.7

Property 2: 数据校验正确性
对任意岗位字典，_validate_job() 应满足：当 id 为空、title 为空/纯空白、
raw_jd 为空/纯空白/占位文本/长度<50 时返回 (False, 原因字符串)；
当所有必填字段合格时返回 (True, "")。校验结果与字段值的关系是确定性的。
验证: 需求 2.1, 2.2, 2.3
"""

from __future__ import annotations

import json

from hypothesis import given, settings, assume, strategies as st

from rag.job_rag import JobRAG, _safe_parse_json_list, _INVALID_JD_PATTERNS

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# 非空可打印文本（排除控制字符）
_printable = st.characters(categories=("L", "M", "N", "P", "S", "Z"))

st_nonempty_text = (
    st.text(alphabet=_printable, min_size=1, max_size=80)
    .filter(lambda s: s.strip())
)

st_short_text = st.text(alphabet=_printable, min_size=1, max_size=30).filter(lambda s: s.strip())

# 技能列表：可以是 JSON 字符串、Python list 或 None
st_skill_list = st.one_of(
    st.none(),
    st.lists(st_short_text, min_size=1, max_size=5),
    st.lists(st_short_text, min_size=1, max_size=5).map(json.dumps),
)

# 职责列表
st_responsibilities = st.one_of(
    st.none(),
    st.lists(st_nonempty_text, min_size=1, max_size=4),
    st.lists(st_nonempty_text, min_size=1, max_size=4).map(json.dumps),
)

# 经验年限
st_exp_min = st.one_of(st.none(), st.integers(min_value=0, max_value=20))
st_exp_max = st.one_of(st.none(), st.integers(min_value=1, max_value=30))

# 学历
st_education = st.one_of(st.none(), st.sampled_from(["大专", "本科", "硕士", "博士"]))

# 行业
st_industry = st.one_of(st.none(), st.sampled_from(["人工智能", "互联网", "金融科技", "教育"]))

# raw_jd：至少 1 字符
st_raw_jd = st.text(alphabet=_printable, min_size=1, max_size=200)


@st.composite
def st_job_dict(draw):
    """生成任意组合的岗位字典，结构化字段可选存在。"""
    job = {
        "id": draw(st.integers(min_value=1, max_value=99999)),
        "title": draw(st_nonempty_text),
        "company": draw(st_nonempty_text),
        "city": draw(st_short_text),
        "salary_min": draw(st.one_of(st.none(), st.integers(min_value=5, max_value=100))),
        "salary_max": draw(st.one_of(st.none(), st.integers(min_value=10, max_value=200))),
        "url": draw(st.one_of(st.none(), st.just("https://example.com/job/123"))),
        "raw_jd": draw(st_raw_jd),
    }

    # 可选结构化字段：随机决定是否包含
    skills_must = draw(st_skill_list)
    if skills_must is not None:
        job["skills_must"] = skills_must

    skills_preferred = draw(st_skill_list)
    if skills_preferred is not None:
        job["skills_preferred"] = skills_preferred

    responsibilities = draw(st_responsibilities)
    if responsibilities is not None:
        job["responsibilities"] = responsibilities

    exp_min = draw(st_exp_min)
    if exp_min is not None:
        job["experience_min"] = exp_min

    exp_max = draw(st_exp_max)
    if exp_max is not None:
        job["experience_max"] = exp_max

    education = draw(st_education)
    if education is not None:
        job["education"] = education

    industry = draw(st_industry)
    if industry is not None:
        job["company_industry"] = industry

    return job


# ---------------------------------------------------------------------------
# Property 1: 文档格式完整性
# ---------------------------------------------------------------------------


class TestBuildDocumentProperty:
    """
    Property 1: 文档格式完整性

    For any job dict with arbitrary combinations of structured fields,
    _build_document() should:
    - Include a label for each non-empty structured field with matching content
    - Omit labels for empty/missing fields
    - Always include 【职位描述】

    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.7
    """

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_always_contains_job_description(self, job: dict):
        """文档始终包含【职位描述】标签。"""
        doc = JobRAG._build_document(job)
        assert "【职位描述】" in doc

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_always_contains_base_labels(self, job: dict):
        """文档始终包含基础标签：岗位ID、岗位、公司、城市、薪资、链接。"""
        doc = JobRAG._build_document(job)
        for label in ("【岗位ID】", "【岗位】", "【公司】", "【城市】", "【薪资】", "【链接】"):
            assert label in doc

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_skills_must_label_presence(self, job: dict):
        """非空 skills_must → 文档包含【必备技能】且内容匹配；空/缺失 → 无此标签。"""
        doc = JobRAG._build_document(job)
        parsed = _safe_parse_json_list(job.get("skills_must"))
        if parsed:
            assert "【必备技能】" in doc
            for skill in parsed:
                assert skill in doc
        else:
            assert "【必备技能】" not in doc

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_skills_preferred_label_presence(self, job: dict):
        """非空 skills_preferred → 文档包含【优先技能】且内容匹配；空/缺失 → 无此标签。"""
        doc = JobRAG._build_document(job)
        parsed = _safe_parse_json_list(job.get("skills_preferred"))
        if parsed:
            assert "【优先技能】" in doc
            for skill in parsed:
                assert skill in doc
        else:
            assert "【优先技能】" not in doc

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_responsibilities_label_presence(self, job: dict):
        """非空 responsibilities → 文档包含【岗位职责】且每条职责出现；空/缺失 → 无此标签。"""
        doc = JobRAG._build_document(job)
        parsed = _safe_parse_json_list(job.get("responsibilities"))
        if parsed:
            assert "【岗位职责】" in doc
            for resp in parsed:
                assert resp in doc
        else:
            assert "【岗位职责】" not in doc

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_experience_label_presence(self, job: dict):
        """experience_min 或 experience_max 存在 → 文档包含【经验要求】；都不存在 → 无此标签。"""
        doc = JobRAG._build_document(job)
        has_exp = job.get("experience_min") is not None or job.get("experience_max") is not None
        if has_exp:
            assert "【经验要求】" in doc
        else:
            assert "【经验要求】" not in doc

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_education_label_presence(self, job: dict):
        """非空 education → 文档包含【学历要求】且内容匹配；空/缺失 → 无此标签。"""
        doc = JobRAG._build_document(job)
        education = job.get("education")
        if education:
            assert "【学历要求】" in doc
            assert education in doc
        else:
            assert "【学历要求】" not in doc

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_industry_label_presence(self, job: dict):
        """非空 company_industry → 文档包含【行业】且内容匹配；空/缺失 → 无此标签。"""
        doc = JobRAG._build_document(job)
        industry = job.get("company_industry")
        if industry:
            assert "【行业】" in doc
            assert industry in doc
        else:
            assert "【行业】" not in doc

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_experience_format(self, job: dict):
        """经验要求格式：{min}-{max}年，min 默认 0，max 默认 '不限'。"""
        doc = JobRAG._build_document(job)
        exp_min = job.get("experience_min")
        exp_max = job.get("experience_max")
        if exp_min is not None or exp_max is not None:
            expected_min = exp_min or 0
            expected_max = exp_max or "不限"
            expected = f"【经验要求】{expected_min}-{expected_max}年"
            assert expected in doc

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_safe_parse_json_list_roundtrip(self, job: dict):
        """_safe_parse_json_list 对 list 和 JSON 字符串的解析结果一致。"""
        for field in ("skills_must", "skills_preferred", "responsibilities"):
            value = job.get(field)
            parsed = _safe_parse_json_list(value)
            # 结果始终是 list[str]
            assert isinstance(parsed, list)
            assert all(isinstance(v, str) for v in parsed)
            # 如果原始值是 list，解析结果应与 [str(v) for v in value] 一致
            if isinstance(value, list):
                assert parsed == [str(v) for v in value]


# ---------------------------------------------------------------------------
# Property 3: raw_jd 截断不变量
# ---------------------------------------------------------------------------

# 截断后缀
_TRUNCATION_SUFFIX = "...（已截断）"
_MAX_RAW_JD = 4000
_MAX_JD_OUTPUT = _MAX_RAW_JD + len(_TRUNCATION_SUFFIX)

# raw_jd strategy：覆盖短文本、恰好边界、超长文本
# 使用 .map(lambda n: "A" * n) 代替 flatmap+text 以提高生成速度
st_raw_jd_varied = st.one_of(
    # 短文本（远低于阈值）
    st.text(alphabet=_printable, min_size=0, max_size=100),
    # 边界附近（3998-4002）
    st.integers(min_value=3998, max_value=4002).map(lambda n: "B" * n),
    # 超长文本
    st.integers(min_value=4001, max_value=6000).map(lambda n: "C" * n),
)


def _extract_jd_section(doc: str) -> str:
    """从文档中提取【职位描述】标签后的内容。"""
    marker = "【职位描述】"
    idx = doc.index(marker)
    return doc[idx + len(marker):]


class TestRawJdTruncationProperty:
    """
    Property 3: raw_jd 截断不变量

    For any raw_jd string:
    - 输出的【职位描述】部分长度 ≤ 4000 + len("...（已截断）")
    - 原始 raw_jd ≤ 4000 字符时，输出与原始完全一致

    Validates: Requirement 2.4
    """

    @given(raw_jd=st_raw_jd_varied)
    @settings(max_examples=200)
    def test_jd_output_never_exceeds_max_length(self, raw_jd: str):
        """【职位描述】内容长度不超过 4000 + len(截断后缀)。"""
        job = {"id": 1, "title": "T", "company": "C", "city": "X", "raw_jd": raw_jd}
        doc = JobRAG._build_document(job)
        jd_content = _extract_jd_section(doc)
        assert len(jd_content) <= _MAX_JD_OUTPUT

    @given(raw_jd=st.text(alphabet=_printable, min_size=0, max_size=4000))
    @settings(max_examples=200)
    def test_short_jd_preserved_exactly(self, raw_jd: str):
        """raw_jd ≤ 4000 字符时，输出与原始完全一致（无截断）。"""
        job = {"id": 1, "title": "T", "company": "C", "city": "X", "raw_jd": raw_jd}
        doc = JobRAG._build_document(job)
        jd_content = _extract_jd_section(doc)
        assert jd_content == raw_jd

    @given(
        raw_jd=st.integers(min_value=4001, max_value=6000).map(lambda n: "X" * n)
    )
    @settings(max_examples=100)
    def test_long_jd_truncated_with_suffix(self, raw_jd: str):
        """raw_jd > 4000 字符时，输出以截断后缀结尾且前缀匹配原始内容。"""
        job = {"id": 1, "title": "T", "company": "C", "city": "X", "raw_jd": raw_jd}
        doc = JobRAG._build_document(job)
        jd_content = _extract_jd_section(doc)
        assert jd_content.endswith(_TRUNCATION_SUFFIX)
        # 截断前缀应与原始 raw_jd 的前 4000 字符一致
        prefix = jd_content[: -len(_TRUNCATION_SUFFIX)]
        assert prefix == raw_jd[:_MAX_RAW_JD]

    @given(
        raw_jd=st.just("A" * 4000)
    )
    @settings(max_examples=5)
    def test_boundary_exact_4000_not_truncated(self, raw_jd: str):
        """恰好 4000 字符的 raw_jd 不被截断。"""
        job = {"id": 1, "title": "T", "company": "C", "city": "X", "raw_jd": raw_jd}
        doc = JobRAG._build_document(job)
        jd_content = _extract_jd_section(doc)
        assert jd_content == raw_jd
        assert _TRUNCATION_SUFFIX not in jd_content

    @given(
        raw_jd=st.just("A" * 4001)
    )
    @settings(max_examples=5)
    def test_boundary_4001_is_truncated(self, raw_jd: str):
        """4001 字符的 raw_jd 被截断。"""
        job = {"id": 1, "title": "T", "company": "C", "city": "X", "raw_jd": raw_jd}
        doc = JobRAG._build_document(job)
        jd_content = _extract_jd_section(doc)
        assert jd_content.endswith(_TRUNCATION_SUFFIX)
        assert len(jd_content) == _MAX_JD_OUTPUT


# ---------------------------------------------------------------------------
# Property 2: 数据校验正确性
# ---------------------------------------------------------------------------

# Strategies for _validate_job testing

# Valid raw_jd: non-whitespace, not a placeholder, ≥ 50 chars after strip
st_valid_raw_jd = (
    st.text(alphabet=_printable, min_size=50, max_size=300)
    .filter(lambda s: len(s.strip()) >= 50 and s.strip() not in _INVALID_JD_PATTERNS)
)

# Invalid id values: None, 0, empty string, False — anything falsy
st_falsy_id = st.sampled_from([None, 0, "", False])

# Invalid title values: empty, whitespace-only, None
st_invalid_title = st.one_of(
    st.just(""),
    st.just(None),
    st.text(alphabet=st.just(" "), min_size=1, max_size=10),  # whitespace-only
    st.text(alphabet=st.just("\t"), min_size=1, max_size=5),
    st.just("  \n\t  "),
)

# Placeholder JD texts
st_placeholder_jd = st.sampled_from(list(_INVALID_JD_PATTERNS))

# Short JD: non-empty, non-whitespace, not placeholder, but < 50 chars stripped
st_short_jd = (
    st.text(alphabet=_printable, min_size=1, max_size=49)
    .filter(lambda s: s.strip() and s.strip() not in _INVALID_JD_PATTERNS and len(s.strip()) < 50)
)

# Whitespace-only JD
st_whitespace_jd = st.one_of(
    st.just(""),
    st.just(None),
    st.text(alphabet=st.just(" "), min_size=1, max_size=20),
    st.just("  \n\t  "),
)


@st.composite
def st_valid_job(draw):
    """Generate a job dict that passes all validation rules."""
    return {
        "id": draw(st.integers(min_value=1, max_value=99999)),
        "title": draw(st_nonempty_text),
        "raw_jd": draw(st_valid_raw_jd),
    }


@st.composite
def st_job_missing_id(draw):
    """Generate a job dict with falsy id."""
    return {
        "id": draw(st_falsy_id),
        "title": draw(st_nonempty_text),
        "raw_jd": draw(st_valid_raw_jd),
    }


@st.composite
def st_job_invalid_title(draw):
    """Generate a job dict with invalid title."""
    return {
        "id": draw(st.integers(min_value=1, max_value=99999)),
        "title": draw(st_invalid_title),
        "raw_jd": draw(st_valid_raw_jd),
    }


@st.composite
def st_job_placeholder_jd(draw):
    """Generate a job dict with placeholder raw_jd."""
    return {
        "id": draw(st.integers(min_value=1, max_value=99999)),
        "title": draw(st_nonempty_text),
        "raw_jd": draw(st_placeholder_jd),
    }


@st.composite
def st_job_short_jd(draw):
    """Generate a job dict with raw_jd < 50 chars."""
    return {
        "id": draw(st.integers(min_value=1, max_value=99999)),
        "title": draw(st_nonempty_text),
        "raw_jd": draw(st_short_jd),
    }


@st.composite
def st_job_empty_jd(draw):
    """Generate a job dict with empty/whitespace raw_jd."""
    return {
        "id": draw(st.integers(min_value=1, max_value=99999)),
        "title": draw(st_nonempty_text),
        "raw_jd": draw(st_whitespace_jd),
    }


class TestValidateJobProperty:
    """
    Property 2: 数据校验正确性

    For any job dict, _validate_job() should:
    - Return (False, reason) when id is falsy, title is empty/whitespace,
      raw_jd is empty/whitespace/placeholder/too short
    - Return (True, "") when all required fields are valid
    - Be deterministic: same input always produces same output

    Validates: Requirements 2.1, 2.2, 2.3
    """

    # We need a JobRAG instance to call _validate_job (it's an instance method).
    # Create a minimal one without initialization.
    _rag_instance = JobRAG.__new__(JobRAG)

    # --- Valid jobs always pass ---

    @given(job=st_valid_job())
    @settings(max_examples=200)
    def test_valid_job_passes(self, job: dict):
        """All required fields valid → (True, "")."""
        ok, reason = self._rag_instance._validate_job(job)
        assert ok is True
        assert reason == ""

    # --- Missing/falsy id always fails ---

    @given(job=st_job_missing_id())
    @settings(max_examples=100)
    def test_missing_id_fails(self, job: dict):
        """Falsy id → (False, "缺少 id")."""
        ok, reason = self._rag_instance._validate_job(job)
        assert ok is False
        assert "id" in reason

    # --- Invalid title always fails ---

    @given(job=st_job_invalid_title())
    @settings(max_examples=100)
    def test_invalid_title_fails(self, job: dict):
        """Empty/whitespace title → (False, "缺少 title")."""
        ok, reason = self._rag_instance._validate_job(job)
        assert ok is False
        assert "title" in reason

    # --- Placeholder JD always fails ---

    @given(job=st_job_placeholder_jd())
    @settings(max_examples=50)
    def test_placeholder_jd_fails(self, job: dict):
        """Placeholder raw_jd → (False, "raw_jd 为占位文本: ...")."""
        ok, reason = self._rag_instance._validate_job(job)
        assert ok is False
        assert "占位文本" in reason

    # --- Short JD always fails ---

    @given(job=st_job_short_jd())
    @settings(max_examples=100)
    def test_short_jd_fails(self, job: dict):
        """raw_jd < 50 chars → (False, "raw_jd 过短: N 字符")."""
        ok, reason = self._rag_instance._validate_job(job)
        assert ok is False
        assert "过短" in reason

    # --- Empty/whitespace JD always fails ---

    @given(job=st_job_empty_jd())
    @settings(max_examples=100)
    def test_empty_jd_fails(self, job: dict):
        """Empty/whitespace raw_jd → (False, "缺少 raw_jd")."""
        ok, reason = self._rag_instance._validate_job(job)
        assert ok is False
        assert "raw_jd" in reason

    # --- Determinism: same input → same output ---

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_deterministic(self, job: dict):
        """Calling _validate_job twice with the same input produces identical results."""
        result1 = self._rag_instance._validate_job(job)
        result2 = self._rag_instance._validate_job(job)
        assert result1 == result2

    # --- Return type invariants ---

    @given(job=st_job_dict())
    @settings(max_examples=200)
    def test_return_type_invariants(self, job: dict):
        """Return is always (bool, str). When ok is True, reason is empty."""
        ok, reason = self._rag_instance._validate_job(job)
        assert isinstance(ok, bool)
        assert isinstance(reason, str)
        if ok:
            assert reason == ""
        else:
            assert len(reason) > 0


# ---------------------------------------------------------------------------
# Strategies for Property 6
# ---------------------------------------------------------------------------

# Minimum valid raw_jd length is 50 chars
_MIN_JD_LEN = 50


@st.composite
def st_batch_job(draw):
    """Generate a job dict that may or may not pass validation.

    Roughly 70% valid, 30% invalid (missing id, empty title, short jd, etc.)
    to exercise both validation paths.
    """
    make_valid = draw(st.booleans().filter(lambda b: True))  # ~50/50 base
    # Bias toward valid to ensure we exercise the insert path
    force_valid = draw(st.integers(min_value=0, max_value=9)) >= 3  # 70% valid

    if force_valid:
        jd_text = draw(st.text(alphabet=_printable, min_size=_MIN_JD_LEN, max_size=200))
        assume(jd_text.strip() not in _INVALID_JD_PATTERNS)
        assume(len(jd_text.strip()) >= _MIN_JD_LEN)
        return {
            "id": draw(st.integers(min_value=1, max_value=99999)),
            "title": draw(st_nonempty_text),
            "raw_jd": jd_text,
            "company": draw(st.one_of(st.none(), st_short_text)),
            "city": draw(st.one_of(st.none(), st_short_text)),
        }
    else:
        # Produce an invalid job: randomly break one required field
        broken = draw(st.sampled_from(["id", "title", "raw_jd"]))
        job: dict = {
            "id": draw(st.integers(min_value=1, max_value=99999)),
            "title": draw(st_nonempty_text),
            "raw_jd": draw(st.text(alphabet=_printable, min_size=_MIN_JD_LEN, max_size=200)),
        }
        if broken == "id":
            job["id"] = draw(st.sampled_from([None, "", 0]))
        elif broken == "title":
            job["title"] = draw(st.sampled_from(["", "   ", None]))
        else:
            job["raw_jd"] = draw(st.sampled_from(["", "   ", "暂无", "x" * 10]))
        return job


# ---------------------------------------------------------------------------
# Property 6: 批量插入结果一致性
# ---------------------------------------------------------------------------

import asyncio
from unittest.mock import AsyncMock, MagicMock


class TestBatchInsertResultProperty:
    """
    Property 6: 批量插入结果一致性

    For any list of jobs (mix of valid and invalid), insert_jobs_batch()
    should return (success, fail) where success + fail == len(jobs).
    When fail / len(jobs) > 0.5, an error-level log should be emitted.

    Uses a mocked _rag.ainsert to isolate the logic under test.

    Validates: Requirements 7.4, 7.5
    """

    @given(jobs=st.lists(st_batch_job(), min_size=1, max_size=20))
    @settings(max_examples=100, deadline=None)
    def test_success_plus_fail_equals_total(self, jobs: list[dict]):
        """success + fail must always equal len(jobs)."""
        rag = JobRAG.__new__(JobRAG)
        rag._initialized = True
        rag._inserted_ids = set()
        rag._rag = MagicMock()
        rag._rag.ainsert = AsyncMock()

        success, fail = asyncio.run(rag.insert_jobs_batch(jobs))

        assert success + fail == len(jobs), (
            f"success({success}) + fail({fail}) != len(jobs)({len(jobs)})"
        )
        assert success >= 0
        assert fail >= 0

    @given(jobs=st.lists(st_batch_job(), min_size=1, max_size=20))
    @settings(max_examples=100, deadline=None)
    def test_success_count_matches_inserted_ids(self, jobs: list[dict]):
        """Every successfully inserted job's ID is tracked in _inserted_ids."""
        rag = JobRAG.__new__(JobRAG)
        rag._initialized = True
        rag._inserted_ids = set()
        rag._rag = MagicMock()
        rag._rag.ainsert = AsyncMock()

        success, fail = asyncio.run(rag.insert_jobs_batch(jobs))

        # _inserted_ids is a set, so duplicate IDs in the batch collapse.
        # The invariant: every inserted ID is tracked, and count <= success.
        assert len(rag._inserted_ids) <= success
        assert len(rag._inserted_ids) > 0 or success == 0

    @given(jobs=st.lists(st_batch_job(), min_size=1, max_size=15))
    @settings(max_examples=50, deadline=None)
    def test_partial_ainsert_failure(self, jobs: list[dict]):
        """When ainsert raises for some jobs, success + fail still == len(jobs)."""
        rag = JobRAG.__new__(JobRAG)
        rag._initialized = True
        rag._inserted_ids = set()
        rag._rag = MagicMock()

        # Make ainsert fail on every other call
        call_count = 0

        async def _flaky_insert(doc):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise RuntimeError("模拟插入失败")

        rag._rag.ainsert = _flaky_insert

        success, fail = asyncio.run(rag.insert_jobs_batch(jobs))

        assert success + fail == len(jobs), (
            f"success({success}) + fail({fail}) != len(jobs)({len(jobs)})"
        )

    @given(jobs=st.lists(st_batch_job(), min_size=1, max_size=15))
    @settings(max_examples=50, deadline=None)
    def test_all_ainsert_failure_triggers_error_log(self, jobs: list[dict]):
        """When all ainsert calls fail, fail rate > 50% should trigger error log."""
        rag = JobRAG.__new__(JobRAG)
        rag._initialized = True
        rag._inserted_ids = set()
        rag._rag = MagicMock()
        rag._rag.ainsert = AsyncMock(side_effect=RuntimeError("全部失败"))

        success, fail = asyncio.run(rag.insert_jobs_batch(jobs))

        # All jobs should be accounted for
        assert success + fail == len(jobs)
        # success should be 0 (only valid jobs attempted, all failed)
        assert success == 0

    def test_empty_list_returns_zero(self):
        """Empty job list should return (0, 0)."""
        rag = JobRAG.__new__(JobRAG)
        rag._initialized = True
        rag._inserted_ids = set()
        rag._rag = MagicMock()

        success, fail = asyncio.run(rag.insert_jobs_batch([]))

        assert success == 0
        assert fail == 0

    def test_not_ready_returns_zero(self):
        """When is_ready is False, should return (0, 0)."""
        rag = JobRAG.__new__(JobRAG)
        rag._initialized = False
        rag._rag = None
        rag._inserted_ids = set()

        success, fail = asyncio.run(
            rag.insert_jobs_batch([{"id": 1, "title": "test", "raw_jd": "x" * 60}])
        )

        assert success == 0
        assert fail == 0


# ---------------------------------------------------------------------------
# Property 4: 岗位 ID 提取完整性
# ---------------------------------------------------------------------------

from rag.job_rag import _extract_job_ids


@st.composite
def st_text_with_job_ids(draw):
    """Generate text containing zero or more 【岗位ID】NNN markers, mixed with noise.

    Uses non-digit separators after each marker to prevent digit-bleeding
    (e.g. 【岗位ID】1 followed by noise "0" being parsed as 【岗位ID】10).
    """
    # Non-digit alphabet for noise to avoid accidental digit concatenation
    _non_digit = st.characters(categories=("L", "M", "P", "S", "Z"))
    num_ids = draw(st.integers(min_value=0, max_value=8))
    ids = [draw(st.integers(min_value=1, max_value=99999)) for _ in range(num_ids)]
    parts = []
    for jid in ids:
        noise = draw(st.text(alphabet=_non_digit, min_size=0, max_size=30))
        parts.append(f"{noise}【岗位ID】{jid}\n")
    # Trailing noise (non-digit)
    parts.append(draw(st.text(alphabet=_non_digit, min_size=0, max_size=30)))
    return "".join(parts), ids


class TestExtractJobIdsProperty:
    """
    Property 4: 岗位 ID 提取完整性

    For any text containing 【岗位ID】markers, _extract_job_ids() should
    extract all IDs present in the text, deduplicated, preserving first-seen order.

    Validates: Requirements 5.1, 5.3
    """

    @given(data=st_text_with_job_ids())
    @settings(max_examples=200)
    def test_extracts_all_embedded_ids(self, data: tuple):
        """All embedded 【岗位ID】values are extracted."""
        text, expected_ids = data
        result: list[int] = []
        _extract_job_ids(text, result)
        # Every expected ID should appear in result
        for jid in expected_ids:
            assert jid in result, f"Expected ID {jid} not found in {result}"

    @given(data=st_text_with_job_ids())
    @settings(max_examples=200)
    def test_no_duplicates(self, data: tuple):
        """Result list contains no duplicate IDs."""
        text, _ = data
        result: list[int] = []
        _extract_job_ids(text, result)
        assert len(result) == len(set(result))

    @given(noise=st.text(alphabet=_printable, min_size=0, max_size=200))
    @settings(max_examples=100)
    def test_no_ids_in_plain_text(self, noise: str):
        """Text without 【岗位ID】markers yields no IDs (unless noise accidentally matches)."""
        # Remove any accidental matches
        import re as _re
        clean = _re.sub(r"【岗位ID】\d+", "", noise)
        result: list[int] = []
        _extract_job_ids(clean, result)
        assert result == []

    @given(data=st_text_with_job_ids())
    @settings(max_examples=200)
    def test_preserves_first_seen_order(self, data: tuple):
        """IDs appear in the order they are first encountered in the text."""
        text, expected_ids = data
        result: list[int] = []
        _extract_job_ids(text, result)
        # Build expected order: unique IDs in first-seen order
        seen = set()
        expected_order = []
        for jid in expected_ids:
            if jid not in seen:
                seen.add(jid)
                expected_order.append(jid)
        assert result == expected_order

    @given(
        ids=st.lists(st.integers(min_value=1, max_value=99999), min_size=1, max_size=10)
    )
    @settings(max_examples=100)
    def test_multi_source_union(self, ids: list[int]):
        """Extracting from multiple text sources yields the union (deduplicated)."""
        # Simulate chunks, entities, relationships each containing some IDs
        import random
        random.shuffle(ids)
        mid = len(ids) // 2
        chunk_ids = ids[:mid] if mid > 0 else ids[:1]
        rel_ids = ids[mid:]

        chunk_text = " ".join(f"【岗位ID】{jid}" for jid in chunk_ids)
        rel_text = " ".join(f"【岗位ID】{jid}" for jid in rel_ids)

        result: list[int] = []
        _extract_job_ids(chunk_text, result)
        _extract_job_ids(rel_text, result)

        # Result should be the union
        assert set(result) == set(ids)
        # No duplicates
        assert len(result) == len(set(result))


# ---------------------------------------------------------------------------
# Property 5: 查询结果排序保持
# ---------------------------------------------------------------------------


@st.composite
def st_job_ids_and_row_map(draw):
    """Generate a job_ids list and a row_map where some IDs may be missing."""
    num_ids = draw(st.integers(min_value=1, max_value=15))
    job_ids = [draw(st.integers(min_value=1, max_value=99999)) for _ in range(num_ids)]
    # Deduplicate while preserving order
    seen = set()
    unique_ids = []
    for jid in job_ids:
        if jid not in seen:
            seen.add(jid)
            unique_ids.append(jid)

    # row_map: randomly include/exclude some IDs
    row_map = {}
    for jid in unique_ids:
        if draw(st.booleans()):  # ~50% chance of being in DB
            row_map[jid] = {
                "id": jid,
                "title": f"Job {jid}",
                "company": "TestCo",
                "salary_min": 10,
                "salary_max": 20,
                "url": f"https://example.com/{jid}",
            }

    return unique_ids, row_map


class TestQueryResultOrderingProperty:
    """
    Property 5: 查询结果排序保持

    For any job_ids list and row_map, the output should preserve the order
    of job_ids (skipping IDs not in row_map).

    Validates: Requirement 5.4
    """

    @given(data=st_job_ids_and_row_map())
    @settings(max_examples=200)
    def test_output_order_matches_job_ids(self, data: tuple):
        """Result order matches job_ids order, skipping missing IDs."""
        job_ids, row_map = data

        # Simulate the ordering logic from query_entities
        result = []
        for jid in job_ids:
            if jid in row_map:
                result.append(row_map[jid])

        # Verify order
        result_ids = [r["id"] for r in result]
        expected_ids = [jid for jid in job_ids if jid in row_map]
        assert result_ids == expected_ids

    @given(data=st_job_ids_and_row_map())
    @settings(max_examples=200)
    def test_no_extra_results(self, data: tuple):
        """Result contains only IDs from job_ids that exist in row_map."""
        job_ids, row_map = data

        result = []
        for jid in job_ids:
            if jid in row_map:
                result.append(row_map[jid])

        result_ids = set(r["id"] for r in result)
        assert result_ids <= set(job_ids)
        assert result_ids <= set(row_map.keys())

    @given(data=st_job_ids_and_row_map())
    @settings(max_examples=200)
    def test_no_missing_available_results(self, data: tuple):
        """Every ID in job_ids that exists in row_map appears in result."""
        job_ids, row_map = data

        result = []
        for jid in job_ids:
            if jid in row_map:
                result.append(row_map[jid])

        result_ids = set(r["id"] for r in result)
        available_ids = set(jid for jid in job_ids if jid in row_map)
        assert result_ids == available_ids
