"""
Property-based tests for FetchJobDetailTool.

# Feature: getjob-data-flow, Property 1: 去重爬取

Property 1: 去重爬取 — 仅对缺失 JD 的岗位发起远程请求
对任意一组 job_ids（混合了有 raw_jd 和无 raw_jd 的岗位），当 force=false 时，
FetchJobDetailTool 应仅对 raw_jd 为空/NULL 的岗位发起远程爬取，
且返回的 skipped 计数应等于已有 raw_jd 的岗位数量。

**Validates: Requirements 1.1, 1.3, 1.4**
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from hypothesis import given, settings
from hypothesis import strategies as st

from db.database import Database
from tools.getjob.fetch_detail import FetchJobDetailTool

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


async def _setup_db_and_jobs(jobs: list[tuple[str | None, str]]) -> tuple:
    """Create an in-memory DB, init schema, insert jobs, return (db, inserted_rows).

    Each element in *jobs* is (raw_jd_value, title_suffix).
    Returns (db, rows) where rows is list of dicts with id, url, raw_jd.
    """
    db = Database(":memory:")
    await db.connect()
    await db.init_schema()

    rows = []
    for idx, (raw_jd, title_suffix) in enumerate(jobs):
        url = f"https://liepin.com/job/{idx}_{title_suffix}"
        title = f"Job_{title_suffix}"
        await db.execute_write(
            "INSERT INTO jobs (url, platform, title, raw_jd) VALUES (?, ?, ?, ?)",
            (url, "liepin", title, raw_jd),
        )
        # Retrieve the inserted row to get the auto-incremented id
        inserted = await db.execute(
            "SELECT id, url, title, raw_jd FROM jobs WHERE url = ?", (url,)
        )
        rows.append(inserted[0])

    return db, rows


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate a non-empty JD string (represents a job that already has JD)
st_has_jd = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())

# Generate a raw_jd value that is either None or empty string (needs fetching)
st_missing_jd = st.one_of(st.none(), st.just(""))

# A single job entry: (raw_jd, unique_suffix)
# raw_jd is either a non-empty string or None/empty
st_job_entry = st.tuples(
    st.one_of(st_has_jd, st_missing_jd),
    st.from_regex(r"[a-z0-9]{1,8}", fullmatch=True),
)

# A list of job entries (1 to 10 jobs, matching the tool's batch limit)
st_job_list = st.lists(st_job_entry, min_size=1, max_size=10, unique_by=lambda x: x[1])


# ---------------------------------------------------------------------------
# Property 1: 去重爬取 — 仅对缺失 JD 的岗位发起远程请求
# ---------------------------------------------------------------------------


class TestFetchDetailDedup:
    """
    Property 1: 去重爬取 — 仅对缺失 JD 的岗位发起远程请求

    For any set of job_ids (mixed with jobs that have raw_jd and jobs that don't),
    when force=false, FetchJobDetailTool should only initiate remote fetching for
    jobs where raw_jd is empty/NULL, and the returned skipped count should equal
    the number of jobs that already have raw_jd.

    **Validates: Requirements 1.1, 1.3, 1.4**
    """

    @given(job_list=st_job_list)
    @settings(max_examples=100)
    def test_skipped_equals_has_jd_count(self, job_list: list[tuple[str | None, str]]):
        """skipped count should equal the number of jobs with non-empty raw_jd."""

        async def _run():
            db, rows = await _setup_db_and_jobs(job_list)
            try:
                job_ids = [r["id"] for r in rows]

                # Count how many jobs already have JD
                has_jd_count = sum(
                    1 for r in rows if r.get("raw_jd") and r["raw_jd"].strip()
                )

                # Mock client that tracks calls
                mock_client = AsyncMock()
                mock_client.fetch_job_detail = AsyncMock(
                    return_value={"success": True, "data": {"jd": "fetched jd text"}}
                )

                tool = FetchJobDetailTool()
                result = await tool.execute(
                    {"job_ids": job_ids, "force": False},
                    {"db": db, "getjob_client": mock_client},
                )

                assert result["skipped"] == has_jd_count, (
                    f"Expected skipped={has_jd_count}, got {result['skipped']}. "
                    f"Jobs: {[(r['id'], r['raw_jd']) for r in rows]}"
                )
            finally:
                await db.close()

        _run_async(_run())

    @given(job_list=st_job_list)
    @settings(max_examples=100)
    def test_remote_fetch_only_for_missing_jd(self, job_list: list[tuple[str | None, str]]):
        """Remote fetch should only be called for jobs with empty/NULL raw_jd."""

        async def _run():
            db, rows = await _setup_db_and_jobs(job_list)
            try:
                job_ids = [r["id"] for r in rows]

                # Identify which jobs need fetching (missing JD)
                missing_jd_urls = {
                    r["url"] for r in rows if not (r.get("raw_jd") and r["raw_jd"].strip())
                }
                # Exclude jobs with invalid URLs
                fetchable_urls = {u for u in missing_jd_urls if u and u != "#"}

                mock_client = AsyncMock()
                mock_client.fetch_job_detail = AsyncMock(
                    return_value={"success": True, "data": {"jd": "fetched jd text"}}
                )

                tool = FetchJobDetailTool()
                await tool.execute(
                    {"job_ids": job_ids, "force": False},
                    {"db": db, "getjob_client": mock_client},
                )

                # Collect all URLs that were actually fetched
                fetched_urls = {
                    call.args[1] for call in mock_client.fetch_job_detail.call_args_list
                }

                # Every fetched URL must be one that was missing JD
                assert fetched_urls <= fetchable_urls, (
                    f"Fetched URLs not in missing-JD set. "
                    f"Extra: {fetched_urls - fetchable_urls}"
                )

                # Every fetchable URL should have been fetched
                assert fetchable_urls <= fetched_urls, (
                    f"Some missing-JD URLs were not fetched. "
                    f"Missing: {fetchable_urls - fetched_urls}"
                )
            finally:
                await db.close()

        _run_async(_run())

    @given(job_list=st_job_list)
    @settings(max_examples=100)
    def test_total_equals_batch_size(self, job_list: list[tuple[str | None, str]]):
        """The total in the result should equal the number of jobs in the batch."""

        async def _run():
            db, rows = await _setup_db_and_jobs(job_list)
            try:
                job_ids = [r["id"] for r in rows]

                mock_client = AsyncMock()
                mock_client.fetch_job_detail = AsyncMock(
                    return_value={"success": True, "data": {"jd": "fetched jd text"}}
                )

                tool = FetchJobDetailTool()
                result = await tool.execute(
                    {"job_ids": job_ids, "force": False},
                    {"db": db, "getjob_client": mock_client},
                )

                assert result["total"] == len(rows), (
                    f"Expected total={len(rows)}, got {result['total']}"
                )
            finally:
                await db.close()

        _run_async(_run())


# ---------------------------------------------------------------------------
# Property 2: 缓存命中返回结构完整
# ---------------------------------------------------------------------------

# Strategy: generate non-empty raw_jd values for cache-hit scenarios
st_raw_jd = st.text(min_size=1, max_size=500).filter(lambda s: s.strip())

# Strategy: generate a title string
st_title = st.from_regex(r"[a-zA-Z0-9_]{1,20}", fullmatch=True)


class TestFetchDetailCacheHitStructure:
    """
    # Feature: getjob-data-flow, Property 2: 缓存命中返回结构完整

    Property 2: 缓存命中返回结构完整
    对于任意已有非空 raw_jd 的岗位，当 force=false 时，FetchJobDetailTool 返回的结果
    应包含 id、title、jd_length、jd_preview 字段，且 source 为 "local_cache"。

    **Validates: Requirements 1.2**
    """

    @given(raw_jd=st_raw_jd, title_suffix=st_title)
    @settings(max_examples=100)
    def test_cache_hit_has_required_fields(self, raw_jd: str, title_suffix: str):
        """Cache hit result must contain id, title, jd_length, jd_preview, and source='local_cache'."""

        async def _run():
            db, rows = await _setup_db_and_jobs([(raw_jd, title_suffix)])
            try:
                job_ids = [rows[0]["id"]]

                mock_client = AsyncMock()
                # Should never be called for cache hits
                mock_client.fetch_job_detail = AsyncMock()

                tool = FetchJobDetailTool()
                result = await tool.execute(
                    {"job_ids": job_ids, "force": False},
                    {"db": db, "getjob_client": mock_client},
                )

                assert result["success"] is True
                assert len(result["results"]) == 1

                item = result["results"][0]
                # All required fields must be present
                assert "id" in item, f"Missing 'id' in result: {item}"
                assert "title" in item, f"Missing 'title' in result: {item}"
                assert "jd_length" in item, f"Missing 'jd_length' in result: {item}"
                assert "jd_preview" in item, f"Missing 'jd_preview' in result: {item}"
                assert item["source"] == "local_cache", (
                    f"Expected source='local_cache', got '{item.get('source')}'"
                )
            finally:
                await db.close()

        _run_async(_run())

    @given(raw_jd=st_raw_jd, title_suffix=st_title)
    @settings(max_examples=100)
    def test_cache_hit_jd_length_matches(self, raw_jd: str, title_suffix: str):
        """jd_length should equal len(raw_jd) and jd_preview should be raw_jd[:200]."""

        async def _run():
            db, rows = await _setup_db_and_jobs([(raw_jd, title_suffix)])
            try:
                job_ids = [rows[0]["id"]]

                mock_client = AsyncMock()
                mock_client.fetch_job_detail = AsyncMock()

                tool = FetchJobDetailTool()
                result = await tool.execute(
                    {"job_ids": job_ids, "force": False},
                    {"db": db, "getjob_client": mock_client},
                )

                item = result["results"][0]
                assert item["jd_length"] == len(raw_jd), (
                    f"Expected jd_length={len(raw_jd)}, got {item['jd_length']}"
                )
                assert item["jd_preview"] == raw_jd[:200], (
                    f"jd_preview mismatch: expected {raw_jd[:200]!r}, got {item['jd_preview']!r}"
                )
            finally:
                await db.close()

        _run_async(_run())

    @given(raw_jd=st_raw_jd, title_suffix=st_title)
    @settings(max_examples=100)
    def test_cache_hit_no_remote_fetch(self, raw_jd: str, title_suffix: str):
        """No remote fetch should be made when cache hits."""

        async def _run():
            db, rows = await _setup_db_and_jobs([(raw_jd, title_suffix)])
            try:
                job_ids = [rows[0]["id"]]

                mock_client = AsyncMock()
                mock_client.fetch_job_detail = AsyncMock()

                tool = FetchJobDetailTool()
                await tool.execute(
                    {"job_ids": job_ids, "force": False},
                    {"db": db, "getjob_client": mock_client},
                )

                mock_client.fetch_job_detail.assert_not_called()
            finally:
                await db.close()

        _run_async(_run())
