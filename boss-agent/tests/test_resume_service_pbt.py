"""
Property-based tests for ResumeService.

Property 1: 标量字段更新往返一致性
通过 update_resume() 写入随机标量字段子集后，get_active_resume() 读取值应与写入值相等。
验证: 需求 1.4, 6.3

Property 2: 列表字段更新往返一致性
通过 update_resume() 写入随机列表字段后，get_active_resume() 读取结构应等价。
验证: 需求 2.3, 3.3, 4.3, 6.4

Property 3: 求职意向更新往返一致性
通过 update_resume() 写入随机 job_preferences 后，读取应等价。
验证: 需求 5.4, 6.5

Property 6: 非法字段拒绝
包含非白名单字段的请求，非法字段被忽略，合法字段正常处理。
验证: 需求 6.2

Property 7: updated_at 时间戳单调递增
连续多次更新后，updated_at 单调非递减。
验证: 需求 6.6
"""

from __future__ import annotations

import asyncio
import time

from hypothesis import given, settings
from hypothesis import strategies as st

from db.database import Database
from web.resume_service import LIST_FIELDS, SCALAR_FIELDS, ResumeService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Helper to run async code in hypothesis tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _create_service() -> ResumeService:
    """Create a ResumeService with a fresh in-memory database."""
    db = Database(":memory:")
    await db.connect()
    await db.init_schema()
    return ResumeService(db)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty printable text for string fields
st_text_value = st.text(
    alphabet=st.characters(categories=("L", "M", "N", "P", "S", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip())

# Integer fields used in scalar context
st_int_value = st.integers(min_value=1950, max_value=2010)
st_years_exp = st.integers(min_value=0, max_value=50)

_STRING_SCALAR_FIELDS = sorted(SCALAR_FIELDS - {"birth_year", "years_of_experience"})
_INT_SCALAR_FIELDS = ["birth_year", "years_of_experience"]


@st.composite
def st_scalar_update(draw):
    """Generate a random subset of scalar fields with appropriate values."""
    # Pick a non-empty subset of scalar fields
    string_fields = draw(
        st.lists(st.sampled_from(_STRING_SCALAR_FIELDS), min_size=0, max_size=len(_STRING_SCALAR_FIELDS), unique=True)
    )
    int_fields = draw(
        st.lists(st.sampled_from(_INT_SCALAR_FIELDS), min_size=0, max_size=len(_INT_SCALAR_FIELDS), unique=True)
    )
    # Ensure at least one field is selected
    if not string_fields and not int_fields:
        string_fields = [draw(st.sampled_from(_STRING_SCALAR_FIELDS))]

    data = {}
    for f in string_fields:
        data[f] = draw(st_text_value)
    for f in int_fields:
        if f == "birth_year":
            data[f] = draw(st_int_value)
        else:
            data[f] = draw(st_years_exp)
    return data


# Work experience entry
@st.composite
def st_work_experience_entry(draw):
    return {
        "company": draw(st_text_value),
        "role": draw(st_text_value),
        "duration": draw(st_text_value),
        "description": draw(st_text_value),
        "tech_stack": draw(st_text_value),
        "highlights": draw(st.lists(st_text_value, min_size=0, max_size=3)),
    }


# Project entry
@st.composite
def st_project_entry(draw):
    return {
        "name": draw(st_text_value),
        "description": draw(st_text_value),
        "tech_stack": draw(st_text_value),
        "highlights": draw(st.lists(st_text_value, min_size=0, max_size=3)),
    }


# Tech stack: dict of category -> list of techs
@st.composite
def st_tech_stack(draw):
    keys = draw(st.lists(st_text_value, min_size=1, max_size=3, unique=True))
    result = {}
    for k in keys:
        result[k] = draw(st.lists(st_text_value, min_size=1, max_size=3))
    return result


@st.composite
def st_list_update(draw):
    """Generate a random subset of list fields with appropriate values."""
    data = {}
    fields = draw(
        st.lists(st.sampled_from(sorted(LIST_FIELDS)), min_size=1, max_size=len(LIST_FIELDS), unique=True)
    )
    for f in fields:
        if f == "work_experience":
            data[f] = draw(st.lists(st_work_experience_entry(), min_size=1, max_size=3))
        elif f == "projects":
            data[f] = draw(st.lists(st_project_entry(), min_size=1, max_size=3))
        elif f == "highlights" or f == "skills_flat":
            data[f] = draw(st.lists(st_text_value, min_size=1, max_size=5))
        elif f == "tech_stack":
            data[f] = draw(st_tech_stack())
    return data


# Job preferences
st_work_type = st.sampled_from(["full_time", "part_time", "remote", "hybrid"])


@st.composite
def st_job_preferences(draw):
    salary_min = draw(st.integers(min_value=1, max_value=50))
    salary_max = draw(st.integers(min_value=salary_min, max_value=100))
    return {
        "target_cities": draw(st.lists(st_text_value, min_size=1, max_size=3)),
        "target_roles": draw(st.lists(st_text_value, min_size=1, max_size=3)),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "work_type": draw(st_work_type),
        "priorities": draw(st.lists(st_text_value, min_size=0, max_size=3)),
        "deal_breakers": draw(st.lists(st_text_value, min_size=0, max_size=3)),
    }


# ---------------------------------------------------------------------------
# Property 1: 标量字段更新往返一致性
# ---------------------------------------------------------------------------


class TestScalarFieldRoundTrip:
    """
    Property 1: 标量字段更新往返一致性

    For any legal subset of scalar fields with random values, after writing
    via update_resume(), reading via get_active_resume() should return
    matching values.

    **Validates: Requirements 1.4, 6.3**
    """

    @given(data=st_scalar_update())
    @settings(max_examples=50, deadline=5000)
    def test_scalar_fields_round_trip(self, data: dict):
        async def _test():
            svc = await _create_service()
            await svc.update_resume(data)
            resume = await svc.get_active_resume()
            assert resume is not None
            for field, expected in data.items():
                actual = resume.get(field)
                assert actual == expected, (
                    f"Field '{field}': expected {expected!r}, got {actual!r}"
                )

        _run_async(_test())

    @given(data=st_scalar_update())
    @settings(max_examples=50, deadline=5000)
    def test_scalar_update_returns_updated_fields(self, data: dict):
        """update_resume should report which fields were updated."""

        async def _test():
            svc = await _create_service()
            result = await svc.update_resume(data)
            assert result["updated"] is True
            for field in data:
                assert field in result["fields"], (
                    f"Field '{field}' not in returned fields list"
                )

        _run_async(_test())


# ---------------------------------------------------------------------------
# Property 2: 列表字段更新往返一致性
# ---------------------------------------------------------------------------


class TestListFieldRoundTrip:
    """
    Property 2: 列表字段更新往返一致性

    For any legal list fields (work_experience, projects, highlights,
    skills_flat, tech_stack), after writing via update_resume(), reading
    via get_active_resume() should return structurally equivalent data.

    **Validates: Requirements 2.3, 3.3, 4.3, 6.4**
    """

    @given(data=st_list_update())
    @settings(max_examples=50, deadline=5000)
    def test_list_fields_round_trip(self, data: dict):
        async def _test():
            svc = await _create_service()
            await svc.update_resume(data)
            resume = await svc.get_active_resume()
            assert resume is not None
            for field, expected in data.items():
                actual = resume.get(field)
                assert actual == expected, (
                    f"Field '{field}': expected {expected!r}, got {actual!r}"
                )

        _run_async(_test())


# ---------------------------------------------------------------------------
# Property 3: 求职意向更新往返一致性
# ---------------------------------------------------------------------------


class TestJobPreferencesRoundTrip:
    """
    Property 3: 求职意向更新往返一致性

    For any legal job_preferences data, after writing via update_resume(),
    reading via get_active_resume() should return equivalent job_preferences.

    **Validates: Requirements 5.4, 6.5**
    """

    @given(prefs=st_job_preferences())
    @settings(max_examples=50, deadline=5000)
    def test_job_preferences_round_trip(self, prefs: dict):
        async def _test():
            svc = await _create_service()
            await svc.update_resume({"job_preferences": prefs})
            resume = await svc.get_active_resume()
            assert resume is not None
            actual_prefs = resume.get("job_preferences")
            assert actual_prefs is not None, "job_preferences should not be None"
            for key, expected in prefs.items():
                actual = actual_prefs.get(key)
                assert actual == expected, (
                    f"job_preferences.{key}: expected {expected!r}, got {actual!r}"
                )

        _run_async(_test())

    @given(prefs=st_job_preferences())
    @settings(max_examples=50, deadline=5000)
    def test_job_preferences_update_existing(self, prefs: dict):
        """Updating job_preferences twice should reflect the latest values."""

        async def _test():
            svc = await _create_service()
            # First write
            await svc.update_resume({"job_preferences": prefs})
            # Second write with modified salary
            updated_prefs = dict(prefs)
            updated_prefs["salary_min"] = prefs["salary_min"] + 1
            updated_prefs["salary_max"] = max(
                updated_prefs["salary_min"], prefs["salary_max"]
            ) + 1
            await svc.update_resume({"job_preferences": updated_prefs})
            resume = await svc.get_active_resume()
            assert resume is not None
            actual_prefs = resume["job_preferences"]
            assert actual_prefs["salary_min"] == updated_prefs["salary_min"]
            assert actual_prefs["salary_max"] == updated_prefs["salary_max"]

        _run_async(_test())


# ---------------------------------------------------------------------------
# Property 6: 非法字段拒绝
# ---------------------------------------------------------------------------

# Generate field names guaranteed NOT to be in the whitelist
_ALL_LEGAL_FIELDS = SCALAR_FIELDS | LIST_FIELDS | {"job_preferences"}
st_illegal_field_name = st.text(
    alphabet=st.characters(categories=("L",)),
    min_size=3,
    max_size=20,
).filter(lambda s: s not in _ALL_LEGAL_FIELDS and s.strip())


class TestIllegalFieldRejection:
    """
    Property 6: 非法字段拒绝

    For any request containing fields NOT in SCALAR_FIELDS or LIST_FIELDS
    whitelist, illegal fields should be ignored and legal fields should be
    processed normally.

    **Validates: Requirements 6.2**
    """

    @given(
        illegal_fields=st.dictionaries(
            st_illegal_field_name,
            st_text_value,
            min_size=1,
            max_size=5,
        ),
        legal_data=st_scalar_update(),
    )
    @settings(max_examples=50, deadline=5000)
    def test_illegal_fields_ignored_legal_fields_processed(
        self, illegal_fields: dict, legal_data: dict
    ):
        async def _test():
            svc = await _create_service()
            # Combine illegal and legal fields
            combined = {**illegal_fields, **legal_data}
            await svc.update_resume(combined)
            resume = await svc.get_active_resume()
            assert resume is not None
            # Legal fields should be stored correctly
            for field, expected in legal_data.items():
                actual = resume.get(field)
                assert actual == expected, (
                    f"Legal field '{field}': expected {expected!r}, got {actual!r}"
                )
            # Illegal fields should NOT appear in the resume
            for field in illegal_fields:
                assert field not in resume or resume.get(field) is None, (
                    f"Illegal field '{field}' should not be in resume"
                )

        _run_async(_test())

    @given(
        illegal_fields=st.dictionaries(
            st_illegal_field_name,
            st_text_value,
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=50, deadline=5000)
    def test_only_illegal_fields_still_creates_resume(self, illegal_fields: dict):
        """Even with only illegal fields, update_resume should still work
        (creating a resume record) but not store illegal data."""

        async def _test():
            svc = await _create_service()
            result = await svc.update_resume(illegal_fields)
            assert result["updated"] is True
            # Illegal fields should not be in the updated fields list
            for field in illegal_fields:
                assert field not in result["fields"], (
                    f"Illegal field '{field}' should not be in updated fields"
                )

        _run_async(_test())


# ---------------------------------------------------------------------------
# Property 7: updated_at 时间戳单调递增
# ---------------------------------------------------------------------------


class TestUpdatedAtMonotonic:
    """
    Property 7: updated_at 时间戳单调递增

    After multiple consecutive updates, updated_at should be monotonically
    non-decreasing.

    **Validates: Requirements 6.6**
    """

    @given(
        updates=st.lists(st_scalar_update(), min_size=2, max_size=4),
    )
    @settings(max_examples=20, deadline=30000)
    def test_updated_at_monotonically_nondecreasing(self, updates: list[dict]):
        async def _test():
            svc = await _create_service()
            timestamps = []
            for update_data in updates:
                await svc.update_resume(update_data)
                resume = await svc.get_active_resume()
                assert resume is not None
                timestamps.append(resume["updated_at"])
                # Sleep to ensure different timestamps (SQLite second precision)
                time.sleep(1.1)

            for i in range(1, len(timestamps)):
                assert timestamps[i] >= timestamps[i - 1], (
                    f"updated_at not monotonic: {timestamps[i-1]} -> {timestamps[i]}"
                )

        _run_async(_test())


# ---------------------------------------------------------------------------
# Property 8: DOCX 内容完整性
# ---------------------------------------------------------------------------


class TestDocxContentCompleteness:
    """
    Property 8: DOCX 内容完整性

    For any resume with all fields populated, export_docx() should produce a
    DOCX whose plain text contains: name, phone, email, summary,
    self_evaluation, each work_experience company & role, each project name,
    each top-level highlight, and job_preferences target_cities & target_roles.

    **Validates: Requirements 7.4, 7.5**
    """

    @given(
        name=st_text_value,
        phone=st_text_value,
        email=st_text_value,
        summary=st_text_value,
        self_evaluation=st_text_value,
        work_entries=st.lists(
            st.fixed_dictionaries({
                "company": st_text_value,
                "role": st_text_value,
                "duration": st_text_value,
                "description": st_text_value,
                "highlights": st.lists(st_text_value, min_size=1, max_size=3),
            }),
            min_size=1,
            max_size=3,
        ),
        project_entries=st.lists(
            st.fixed_dictionaries({
                "name": st_text_value,
                "description": st_text_value,
                "highlights": st.lists(st_text_value, min_size=1, max_size=3),
            }),
            min_size=1,
            max_size=3,
        ),
        top_highlights=st.lists(st_text_value, min_size=1, max_size=5),
        target_cities=st.lists(st_text_value, min_size=1, max_size=3),
        target_roles=st.lists(st_text_value, min_size=1, max_size=3),
    )
    @settings(max_examples=30, deadline=30000)
    def test_docx_contains_all_key_content(
        self,
        name,
        phone,
        email,
        summary,
        self_evaluation,
        work_entries,
        project_entries,
        top_highlights,
        target_cities,
        target_roles,
    ):
        import io

        from docx import Document as DocxDocument

        async def _test():
            svc = await _create_service()

            data = {
                "name": name,
                "phone": phone,
                "email": email,
                "summary": summary,
                "self_evaluation": self_evaluation,
                "work_experience": work_entries,
                "projects": project_entries,
                "highlights": top_highlights,
                "job_preferences": {
                    "target_cities": target_cities,
                    "target_roles": target_roles,
                    "salary_min": 20,
                    "salary_max": 40,
                    "work_type": "full_time",
                },
            }
            await svc.update_resume(data)

            docx_bytes, _ = await svc.export_docx()

            # Extract plain text from DOCX
            doc = DocxDocument(io.BytesIO(docx_bytes))
            full_text = "\n".join(p.text for p in doc.paragraphs)

            # Verify key content present
            assert name in full_text, f"name '{name}' not found in DOCX"
            assert phone in full_text, f"phone '{phone}' not found"
            assert email in full_text, f"email '{email}' not found"
            assert summary in full_text, "summary not found"
            assert self_evaluation in full_text, "self_evaluation not found"

            for entry in work_entries:
                assert entry["company"] in full_text, (
                    f"work company '{entry['company']}' not found"
                )
                assert entry["role"] in full_text, (
                    f"work role '{entry['role']}' not found"
                )

            for proj in project_entries:
                assert proj["name"] in full_text, (
                    f"project name '{proj['name']}' not found"
                )

            for h in top_highlights:
                assert h in full_text, f"highlight '{h}' not found"

            for city in target_cities:
                assert city in full_text, f"target city '{city}' not found"

            for role in target_roles:
                assert role in full_text, f"target role '{role}' not found"

        _run_async(_test())


# ---------------------------------------------------------------------------
# Property 9: DOCX 文件名格式
# ---------------------------------------------------------------------------


class TestDocxFilenameFormat:
    """
    Property 9: DOCX 文件名格式

    For any resume with a name, export_docx() should return a filename
    matching the pattern: 简历_{name}_{YYYYMMDD}.docx

    **Validates: Requirements 7.6**
    """

    @given(name=st_text_value)
    @settings(max_examples=50, deadline=30000)
    def test_docx_filename_matches_pattern(self, name):
        import re
        from datetime import datetime

        async def _test():
            svc = await _create_service()
            await svc.update_resume({"name": name})

            _, filename = await svc.export_docx()

            today = datetime.now().strftime("%Y%m%d")
            expected = f"简历_{name}_{today}.docx"
            assert filename == expected, (
                f"Expected filename '{expected}', got '{filename}'"
            )

            # Also verify it matches the general pattern
            pattern = r"^简历_.+_\d{8}\.docx$"
            assert re.match(pattern, filename), (
                f"Filename '{filename}' doesn't match pattern"
            )

        _run_async(_test())
