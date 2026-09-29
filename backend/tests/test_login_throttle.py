"""
Login throttling tests.

The point of these is not that a counter increments. It is that the four ways a
throttle usually goes wrong are closed:

- it lets the attacker's last, correct guess through
- it locks out every teacher at a school sharing one connection
- it lets an attacker lock a named teacher out of their own account
- it never releases, or releases because a clock was slept through in a test
"""

from __future__ import annotations

import pytest
from app import throttle
from app.db import get_session
from app.main import app
from app.models import Teacher
from app.security import ROLE_TEACHER, hash_password
from fastapi.testclient import TestClient
from sqlalchemy import select

from .test_repository import session  # noqa: F401 - pytest fixture

GOOD = "correct-horse"
BAD = "not-the-password"


@pytest.fixture
def client(session):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def teacher(session):  # noqa: F811
    t = session.scalar(select(Teacher))
    t.password_hash = hash_password(GOOD)
    t.role = ROLE_TEACHER
    session.commit()
    return t


def attempt(client, email, password, headers=None):
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=headers or {},
    )


def exhaust(client, email, password=BAD):
    """Use up the whole allowance without tripping it."""
    for _ in range(throttle.MAX_ATTEMPTS):
        assert attempt(client, email, password).status_code == 401


def test_repeated_failures_are_eventually_refused(client, teacher):
    exhaust(client, teacher.email)
    r = attempt(client, teacher.email, BAD)
    assert r.status_code == 429


def test_refusal_says_when_to_come_back(client, teacher):
    exhaust(client, teacher.email)
    r = attempt(client, teacher.email, BAD)
    assert int(r.headers["Retry-After"]) > 0
    # And it does not leak whether the account exists.
    assert "password" not in r.json()["detail"].lower()


def test_the_correct_password_is_also_refused_while_throttled(client, teacher):
    """The attacker's successful guess is precisely the one to stop."""
    exhaust(client, teacher.email)
    assert attempt(client, teacher.email, GOOD).status_code == 429


def test_a_successful_sign_in_clears_the_count(client, teacher):
    for _ in range(throttle.MAX_ATTEMPTS - 1):
        assert attempt(client, teacher.email, BAD).status_code == 401

    assert attempt(client, teacher.email, GOOD).status_code == 200

    # The allowance is whole again, so the next wrong password is a 401 and not
    # a carried-over 429.
    assert attempt(client, teacher.email, BAD).status_code == 401


def test_throttling_one_account_does_not_affect_another(client, teacher):
    exhaust(client, teacher.email)
    assert attempt(client, teacher.email, BAD).status_code == 429
    # A different account from the same address is unaffected: otherwise five
    # wrong guesses would lock out everyone sharing a school's connection.
    assert attempt(client, "someone.else@example.school", BAD).status_code == 401


def test_throttling_one_address_does_not_affect_another(client, teacher, monkeypatch):
    """A teacher locked out from one place can still sign in from another."""
    monkeypatch.setattr(throttle, "TRUST_PROXY_HEADER", True)
    attacker = {"X-Forwarded-For": "10.0.0.1"}
    victim = {"X-Forwarded-For": "10.0.0.2"}

    for _ in range(throttle.MAX_ATTEMPTS):
        assert attempt(client, teacher.email, BAD, attacker).status_code == 401
    assert attempt(client, teacher.email, BAD, attacker).status_code == 429

    assert attempt(client, teacher.email, GOOD, victim).status_code == 200


def test_the_window_expires(client, teacher, monkeypatch):
    """Without this the throttle is a permanent ban. The clock is advanced
    rather than slept through, so the test stays fast and deterministic."""
    clock = [1000.0]
    monkeypatch.setattr(throttle, "_now", lambda: clock[0])

    exhaust(client, teacher.email)
    assert attempt(client, teacher.email, BAD).status_code == 429

    clock[0] += throttle.WINDOW_SECONDS + 1
    assert attempt(client, teacher.email, GOOD).status_code == 200


def test_forwarded_header_is_ignored_unless_trusted(client, teacher):
    """Trusting it by default would let an attacker send a new address each
    attempt and never be throttled at all."""
    assert throttle.TRUST_PROXY_HEADER is False

    for i in range(throttle.MAX_ATTEMPTS):
        spoofed = {"X-Forwarded-For": f"10.0.0.{i}"}
        assert attempt(client, teacher.email, BAD, spoofed).status_code == 401

    assert attempt(client, teacher.email, BAD, {"X-Forwarded-For": "10.0.0.99"}).status_code == 429


def test_state_does_not_grow_without_bound(client, teacher, monkeypatch):
    """An attacker cycling addresses must not be able to exhaust memory."""
    clock = [1000.0]
    monkeypatch.setattr(throttle, "_now", lambda: clock[0])
    monkeypatch.setattr(throttle, "TRUST_PROXY_HEADER", True)

    for i in range(20):
        attempt(client, teacher.email, BAD, {"X-Forwarded-For": f"10.1.0.{i}"})
    assert len(throttle._failures) == 20

    # Once the window has passed, the next request sweeps the stale keys out.
    clock[0] += throttle.WINDOW_SECONDS + throttle._SWEEP_EVERY_SECONDS + 1
    attempt(client, teacher.email, BAD, {"X-Forwarded-For": "10.2.0.1"})
    assert len(throttle._failures) == 1
