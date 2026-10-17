"""
Shared test setup.

Login throttling keeps counters in module-level state, which would otherwise
leak between tests: a test that fails a login five times would throttle an
unrelated test that logs in afterwards. Clearing it before every test keeps
each one independent, regardless of the order pytest chooses.

The embedder stub is here rather than in one test module because starting a
`TestClient` runs the application's lifespan, and the lifespan now warms the
sentence-transformer. Warming is skipped when an embedder is already
installed, so installing a stub before every test is what keeps a 90MB
download out of a suite that is meant to run offline in seconds.
"""

from __future__ import annotations

import pytest
from app import curriculum, throttle


@pytest.fixture(autouse=True)
def _clear_login_throttle():
    throttle.reset()
    yield
    throttle.reset()


@pytest.fixture(autouse=True)
def _never_the_real_model():
    curriculum.set_embedder(lambda texts: [[0.0] * 384 for _ in texts])
    yield
    curriculum.set_embedder(None)
