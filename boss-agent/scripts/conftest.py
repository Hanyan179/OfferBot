"""
conftest for scripts/ e2e tests.

Suppresses RuntimeError('Event loop is closed') from httpx/OpenAI client
cleanup during test teardown — a known issue with Python 3.14 + anyio.
"""

import pytest


def _is_event_loop_closed(exc: BaseException) -> bool:
    """Check if exception is the known event-loop-closed pattern."""
    if isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return all(_is_event_loop_closed(e) for e in exc.exceptions)
    return False


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Suppress event-loop-closed errors raised during async test execution."""
    outcome = yield
    excinfo = outcome.excinfo
    if excinfo is not None:
        exc = excinfo[1]
        if _is_event_loop_closed(exc):
            outcome.force_result(None)
