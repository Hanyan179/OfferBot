"""
Property-based and unit tests for sync filtering, upsert protection, and auto-sync callback.

# Feature: getjob-data-flow, Property 4: 同步过滤正确性与统计一致性
# Feature: getjob-data-flow, Property 7: Upsert 保留已有 raw_jd

**Validates: Requirements 3.3, 3.4, 5.2, 2.2, 2.3, 2.4**
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from db.database import Database
from tools.getjob.platform_sync import _filter_rows, _normalize_city, _upsert_jobs


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


# ---------------------------------------------------------------------------
# Strategies for Property 4
# ---------------------------------------------------------------------------

# Chinese city names with optional district suffixes
st_city_base = st.sampled_from(["上海", "北京", "深圳", "杭州", "广州", "成都", "南京"])
st_district = st.sampled_from(["", "-浦东新区", "-朝阳区", "·西湖区", "-南山区", ""])
st_city_full = st.tuples(st_city_base, st_district).map(lambda t: t[0] + t[1])

# Salary values: either None (面议) or a positive integer
st_salary_val = st.one_of(st.none(), st.integers(min_value=1, max_value=200))

# A single job row dict for _filter_rows
st_job_row = st.fixed_dictionaries({
    "url": st.one_of(st.just(""), st.from_regex(r"https://[a-z]+\.com/job/[0-9]{1,6}", fullmatch=True)),
    "title": st.from_regex(r"[a-zA-Z0-9_]{1,10}", fullmatch=True),
    "company": st.just("TestCo"),
    "city": st.one_of(st.just(""), st_city_full),
    "salary_min": st_salary_val,
    "salary_max": st_salary_val,
    "platform": st.just("liepin"),
})

# Ensure salary_min <= salary_max when both are present
def _fix_salary(row: dict) -> dict:
    row = dict(row)
    if row["salary_min"] is not None and row["salary_max"] is not None:
        if row["salary_min"] > row["salary_max"]:
            row["salary_min"], row["salary_max"] = row["salary_max"], row["salary_min"]
    return row

st_job_row_fixed = st_job_row.map(_fix_salary)

# List of job rows
st_job_rows = st.lists(st_job_row_fixed, min_size=0, max_size=20)

# Filter parameters
st_filter_city = st.one_of(st.none(), st_city_base)
st_filter_salary_min = st.one_of(st.none(), st.integers(min_value=1, max_value=100))
st_filter_salary_max = st.one_of(st.none(), st.integers(min_value=1, max_value=200))


# ---------------------------------------------------------------------------
# Property 4: 同步过滤正确性与统计一致性
# ---------------------------------------------------------------------------


class TestFilterRowsProperty:
    """
    # Feature: getjob-data-flow, Property 4: 同步过滤正确性与统计一致性

    For any set of job rows and filter conditions (city, salary range),
    _filter_rows should:
    - Discard rows with empty URL
    - Discard rows with city mismatch (fuzzy match via _normalize_city)
    - Discard rows with salary mismatch (when both sides have data)
    - Preserve 面议 jobs (salary=None)
    - Stats invariant: total = passed + city_mismatch + salary_mismatch + no_url

    **Validates: Requirements 3.3, 3.4**
    """

    @given(rows=st_job_rows, city=st_filter_city,
           sal_min=st_filter_salary_min, sal_max=st_filter_salary_max)
    @settings(max_examples=100)
    def test_stats_invariant(self, rows, city, sal_min, sal_max):
        """total = passed + city_mismatch + salary_mismatch + no_url"""
        _, stats = _filter_rows(rows, city=city, salary_min_k=sal_min, salary_max_k=sal_max)

        assert stats["total"] == len(rows)
        assert stats["total"] == (
            stats["passed"] + stats["city_mismatch"]
            + stats["salary_mismatch"] + stats["no_url"]
        ), f"Stats invariant violated: {stats}"

    @given(rows=st_job_rows, city=st_filter_city,
           sal_min=st_filter_salary_min, sal_max=st_filter_salary_max)
    @settings(max_examples=100)
    def test_no_url_discarded(self, rows, city, sal_min, sal_max):
        """Rows with empty URL must not appear in filtered output."""
        filtered, stats = _filter_rows(rows, city=city, salary_min_k=sal_min, salary_max_k=sal_max)

        no_url_count = sum(1 for r in rows if not r.get("url"))
        assert stats["no_url"] == no_url_count
        for r in filtered:
            assert r.get("url"), "Filtered row has empty URL"

    @given(rows=st_job_rows, city=st_filter_city,
           sal_min=st_filter_salary_min, sal_max=st_filter_salary_max)
    @settings(max_examples=100)
    def test_mianyi_preserved(self, rows, city, sal_min, sal_max):
        """Jobs with salary=None (面议) should not be filtered by salary."""
        filtered, _ = _filter_rows(rows, city=city, salary_min_k=sal_min, salary_max_k=sal_max)

        # Collect 面议 jobs that have a valid URL and matching city
        target_city = _normalize_city(city) if city else None
        for r in rows:
            if not r.get("url"):
                continue
            if target_city:
                row_city = _normalize_city(r.get("city", ""))
                if row_city and target_city not in row_city and row_city not in target_city:
                    continue
            # If both salary_min and salary_max are None, it's 面议 — should be in filtered
            if r.get("salary_min") is None and r.get("salary_max") is None:
                assert r in filtered, f"面议 job should be preserved: {r}"

    @given(rows=st_job_rows, city=st_filter_city,
           sal_min=st_filter_salary_min, sal_max=st_filter_salary_max)
    @settings(max_examples=100)
    def test_city_fuzzy_match(self, rows, city, sal_min, sal_max):
        """City matching uses _normalize_city: '上海-浦东新区' matches '上海'."""
        filtered, _ = _filter_rows(rows, city=city, salary_min_k=sal_min, salary_max_k=sal_max)

        if not city:
            return  # No city filter, skip

        target = _normalize_city(city)
        for r in filtered:
            row_city = _normalize_city(r.get("city", ""))
            # Empty city rows pass through (no city to mismatch)
            if row_city:
                assert (target in row_city or row_city in target), (
                    f"City mismatch in filtered: row_city={row_city!r}, target={target!r}"
                )

    @given(rows=st_job_rows, city=st_filter_city,
           sal_min=st_filter_salary_min, sal_max=st_filter_salary_max)
    @settings(max_examples=100)
    def test_passed_count_matches_filtered_len(self, rows, city, sal_min, sal_max):
        """stats['passed'] should equal len(filtered)."""
        filtered, stats = _filter_rows(rows, city=city, salary_min_k=sal_min, salary_max_k=sal_max)
        assert stats["passed"] == len(filtered), (
            f"passed={stats['passed']} != len(filtered)={len(filtered)}"
        )


# ---------------------------------------------------------------------------
# Property 7: Upsert 保留已有 raw_jd
# ---------------------------------------------------------------------------

# Strategy for raw_jd values
st_raw_jd = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())
st_title = st.from_regex(r"[a-zA-Z0-9_]{1,15}", fullmatch=True)
st_company = st.from_regex(r"[a-zA-Z0-9_]{1,15}", fullmatch=True)


class TestUpsertPreservesRawJd:
    """
    # Feature: getjob-data-flow, Property 7: Upsert 保留已有 raw_jd

    For any job that already has a non-empty raw_jd, when _upsert_jobs updates
    other fields (title, company, etc.) via the same URL, the raw_jd value
    should remain unchanged because the ON CONFLICT clause does not include raw_jd.

    **Validates: Requirements 5.2**
    """

    @given(raw_jd=st_raw_jd, new_title=st_title, new_company=st_company)
    @settings(max_examples=100)
    def test_upsert_preserves_existing_raw_jd(self, raw_jd, new_title, new_company):
        """Upserting a job with the same URL should not overwrite existing raw_jd."""

        async def _run():
            db = Database(":memory:")
            await db.connect()
            await db.init_schema()
            try:
                url = "https://liepin.com/job/test_upsert_001"

                # Step 1: Insert a job with raw_jd
                await db.execute_write(
                    "INSERT INTO jobs (url, platform, title, company, raw_jd) VALUES (?, ?, ?, ?, ?)",
                    (url, "liepin", "OriginalTitle", "OriginalCo", raw_jd),
                )

                # Verify raw_jd was inserted
                before = await db.execute("SELECT raw_jd FROM jobs WHERE url = ?", (url,))
                assert before[0]["raw_jd"] == raw_jd

                # Step 2: Upsert the same job with different title/company via _upsert_jobs
                upsert_row = {
                    "url": url,
                    "title": new_title,
                    "company": new_company,
                    "salary_min": 20,
                    "salary_max": 40,
                    "salary_months": None,
                    "city": "上海",
                    "experience": "3-5年",
                    "education": "本科",
                    "company_industry": "互联网",
                    "company_size": "100-499人",
                    "recruiter_name": "HR",
                    "recruiter_title": "招聘经理",
                    "platform": "liepin",
                }
                inserted, updated = await _upsert_jobs(db, [upsert_row])
                assert updated == 1, f"Expected 1 update, got inserted={inserted}, updated={updated}"

                # Step 3: Verify raw_jd is unchanged
                after = await db.execute("SELECT raw_jd, title, company FROM jobs WHERE url = ?", (url,))
                assert after[0]["raw_jd"] == raw_jd, (
                    f"raw_jd changed! Before: {raw_jd!r}, After: {after[0]['raw_jd']!r}"
                )
                # Also verify other fields were updated
                assert after[0]["title"] == new_title
                assert after[0]["company"] == new_company
            finally:
                await db.close()

        _run_async(_run())


# ---------------------------------------------------------------------------
# 5.3 Unit tests: 自动同步回调与通知
# ---------------------------------------------------------------------------


class TestAutoSyncCallbackAndNotification:
    """
    Unit tests for PlatformStartTaskTool auto-sync callback and notifications.

    - platform_start_task builds on_complete callback and passes it to TaskMonitor
    - on_complete success notification includes sync stats
    - on_complete failure notification includes error info

    **Validates: Requirements 2.2, 2.3, 2.4**
    """

    def test_start_task_passes_on_complete_to_monitor(self):
        """PlatformStartTaskTool should build on_complete and pass it to TaskMonitor.start_polling."""
        from tools.getjob.platform_control import PlatformStartTaskTool

        async def _run():
            tool = PlatformStartTaskTool()

            mock_client = AsyncMock()
            mock_client.start_task = AsyncMock(return_value={
                "success": True,
                "data": {"status": "started"},
            })

            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=[{"cnt": 0}])

            mock_monitor = MagicMock()
            mock_monitor.start_polling = MagicMock()

            context = {
                "getjob_client": mock_client,
                "db": mock_db,
                "task_monitor": mock_monitor,
            }

            result = await tool.execute({"platform": "liepin"}, context)
            assert result["success"] is True

            # Verify start_polling was called with on_complete
            mock_monitor.start_polling.assert_called_once()
            call_kwargs = mock_monitor.start_polling.call_args
            # on_complete should be passed as a keyword argument
            assert call_kwargs.kwargs.get("on_complete") is not None or \
                   (len(call_kwargs.args) >= 8 and call_kwargs.args[7] is not None), \
                "on_complete callback not passed to start_polling"

        _run_async(_run())

    def test_on_complete_success_notification_includes_sync_stats(self):
        """When on_complete succeeds, the notification message should include sync stats."""
        from services.task_monitor import TaskMonitor, TaskNotification

        async def _run():
            monitor = TaskMonitor()
            notifications = []

            # Mock the enqueue to capture notifications
            original_enqueue = monitor.enqueue
            async def capture_enqueue(notification):
                notifications.append(notification)
                # Don't call original to avoid lock issues in test
            monitor.enqueue = capture_enqueue

            # Simulate on_complete that returns sync stats
            async def mock_on_complete(platform: str) -> dict:
                return {
                    "success": True,
                    "data": {
                        "total_fetched": 50,
                        "inserted": 30,
                        "updated": 20,
                    },
                }

            mock_client = AsyncMock()
            # First poll: isRunning=True, second poll: isRunning=False
            mock_client.get_status = AsyncMock(side_effect=[
                {"success": True, "data": {"isRunning": True}},
                {"success": True, "data": {"isRunning": False}},
            ])

            # Run the poll loop directly
            await monitor._poll_loop(
                task_id="task_liepin",
                platform="liepin",
                client=mock_client,
                poll_interval=0.01,
                max_polls=10,
                agent_busy_check=None,
                progress_callback=None,
                on_complete=mock_on_complete,
            )

            assert len(notifications) == 1
            n = notifications[0]
            assert n.status == "completed"
            assert "50" in n.message or "拉取" in n.message
            assert "30" in n.message or "新增" in n.message
            assert "20" in n.message or "更新" in n.message
            assert n.data.get("sync_result") is not None

        _run_async(_run())

    def test_on_complete_failure_notification_includes_error(self):
        """When on_complete fails, the notification should still be created with error info."""
        from services.task_monitor import TaskMonitor, TaskNotification

        async def _run():
            monitor = TaskMonitor()
            notifications = []

            async def capture_enqueue(notification):
                notifications.append(notification)
            monitor.enqueue = capture_enqueue

            # on_complete that raises an exception
            async def failing_on_complete(platform: str) -> dict:
                raise RuntimeError("Sync database connection failed")

            mock_client = AsyncMock()
            mock_client.get_status = AsyncMock(side_effect=[
                {"success": True, "data": {"isRunning": False}},
            ])

            await monitor._poll_loop(
                task_id="task_liepin",
                platform="liepin",
                client=mock_client,
                poll_interval=0.01,
                max_polls=10,
                agent_busy_check=None,
                progress_callback=None,
                on_complete=failing_on_complete,
            )

            assert len(notifications) == 1
            n = notifications[0]
            assert n.status == "completed"
            # The sync_result in data should contain the error
            sync_result = n.data.get("sync_result", {})
            assert "error" in sync_result
            assert "Sync database connection failed" in sync_result["error"]

        _run_async(_run())
