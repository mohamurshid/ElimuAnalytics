"""
Shared test setup.

Login throttling keeps counters in module-level state, which would otherwise
leak between tests: a test that fails a login five times would throttle an
unrelated test that logs in afterwards. Clearing it before every test keeps
each one independent, regardless of the order pytest chooses.
"""

from __future__ import annotations

import pytest
from app import throttle


@pytest.fixture(autouse=True)
def _clear_login_throttle():
    throttle.reset()
    yield
    throttle.reset()
