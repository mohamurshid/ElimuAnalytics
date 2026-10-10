"""
Refresh-token tests.

The feature exists so that a teacher who reloads the page is not signed out,
while nothing readable by page script is long-lived. Four properties carry
that, and each is tested:

1. the refresh cookie is **httpOnly** - if it is not, the whole design is
   pointless, because an injected script could read it like any other value
2. refreshing **rotates** - a token is spent the moment it is used
3. a **retired token presented again revokes the family** - this is what
   turns a stolen refresh token from indefinite access into one short session
4. **logout revokes**, so signing out is not merely a client-side gesture

The fourth is easy to get wrong in a way nobody notices: a logout that only
clears the cookie leaves a perfectly valid credential in whoever else's hands.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from app.db import get_session
from app.main import app
from app.models import RefreshToken, Teacher
from app.security import REFRESH_COOKIE, ROLE_SCHOOL_ADMIN, hash_password, hash_refresh_token
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from .test_repository import session  # noqa: F401 - pytest fixture

PASSWORD = "correct-horse"


@pytest.fixture
def client(session):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def account(session):  # noqa: F811
    t = session.scalar(select(Teacher))
    t.password_hash = hash_password(PASSWORD)
    t.role = ROLE_SCHOOL_ADMIN
    session.commit()
    return t


def sign_in(client, account):
    r = client.post(
        "/api/auth/login", json={"email": account.email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return r


def cookie_header(response) -> str:
    return response.headers.get("set-cookie", "")


def refresh_cookie(response) -> str:
    """The token the server just set, read from the response header.

    Read from the header rather than the client's jar, because the jar can
    hold more than one cookie of this name and asking it for one then raises.
    """
    for key, value in response.headers.multi_items():
        if key.lower() == "set-cookie" and value.startswith(REFRESH_COOKIE + "="):
            return value.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("the response set no refresh cookie")


def use_cookie(client, raw: str) -> dict:
    """Send exactly this refresh cookie, and nothing else.

    Returns headers to pass to the request, having first emptied the jar.

    The jar is avoided on purpose. `client.cookies.set()` ADDS a cookie rather
    than replacing one when the domain or path differ, so setting a forged
    value leaves two cookies of the same name and sends whichever the jar
    orders first - which differs between httpx versions. Two of these tests
    passed on one machine and failed on another for that reason alone, while
    the server behaved identically on both. An explicit header over an empty
    jar depends on nothing version-specific.
    """
    client.cookies.clear()
    return {"Cookie": f"{REFRESH_COOKIE}={raw}"}


# --- the cookie ------------------------------------------------------------
def test_login_sets_an_httponly_refresh_cookie(client, account):
    r = sign_in(client, account)
    header = cookie_header(r).lower()

    assert REFRESH_COOKIE in header
    assert "httponly" in header, "a readable cookie defeats the entire design"
    assert "samesite" in header
    assert "path=/api/auth" in header


def test_the_refresh_token_is_not_in_the_response_body(client, account):
    """Anything in the body is readable by page script, which is what the
    cookie exists to avoid."""
    body = sign_in(client, account).json()
    assert set(body) == {"access_token", "token_type", "role", "name"}


def test_only_a_hash_of_the_token_is_stored(client, account, session):  # noqa: F811
    """A database disclosure must not hand over usable credentials."""
    r = sign_in(client, account)
    raw = refresh_cookie(r)
    stored = session.scalar(select(RefreshToken))

    assert raw and raw not in stored.token_hash
    assert stored.token_hash == hash_refresh_token(raw)
    assert len(stored.token_hash) == 64  # sha256 hex
    assert r.json()["access_token"]


# --- rotation --------------------------------------------------------------
def test_refresh_returns_a_new_access_token(client, account):
    sign_in(client, account)
    r = client.post("/api/auth/refresh")

    assert r.status_code == 200
    assert r.json()["access_token"]
    assert r.json()["role"] == ROLE_SCHOOL_ADMIN


def test_refreshing_rotates_the_token(client, account, session):  # noqa: F811
    first = refresh_cookie(sign_in(client, account))

    second = refresh_cookie(client.post("/api/auth/refresh", headers=use_cookie(client, first)))

    assert first != second
    spent = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(first))
    )
    assert spent.revoked is True


def test_the_new_access_token_works(client, account):
    sign_in(client, account)
    token = client.post("/api/auth/refresh").json()["access_token"]

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == account.email


def test_refresh_without_a_cookie_is_refused(client):
    assert client.post("/api/auth/refresh").status_code == 401


def test_a_forged_cookie_is_refused(client, account):
    sign_in(client, account)
    forged = use_cookie(client, "not-a-real-token")
    assert client.post("/api/auth/refresh", headers=forged).status_code == 401


# --- reuse detection -------------------------------------------------------
def test_reusing_a_spent_token_kills_the_whole_family(client, account, session):  # noqa: F811
    """The property that limits the damage of a stolen refresh token.

    An attacker who copies the cookie and uses it causes the legitimate
    client's next refresh to present a retired token - or the reverse. Either
    way the server cannot tell the thief from the owner, so both are signed
    out and the owner notices.
    """
    stolen = refresh_cookie(sign_in(client, account))

    rotate = client.post("/api/auth/refresh", headers=use_cookie(client, stolen))
    current = refresh_cookie(rotate)  # `stolen` is now spent

    live = client.post("/api/auth/refresh", headers=use_cookie(client, current))
    assert live.status_code == 200  # the current one still works

    replay = client.post("/api/auth/refresh", headers=use_cookie(client, stolen))
    assert replay.status_code == 401
    assert "reused" in replay.json()["detail"]

    live = session.scalar(
        select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked.is_(False))
    )
    assert live == 0, "every token in the family should be revoked"


# --- expiry ----------------------------------------------------------------
def test_an_expired_token_is_refused(client, account, session):  # noqa: F811
    sign_in(client, account)
    stored = session.scalar(select(RefreshToken))
    stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()

    r = client.post("/api/auth/refresh")
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


# --- logout ----------------------------------------------------------------
def test_logout_revokes_rather_than_just_forgetting(client, account, session):  # noqa: F811
    """Clearing the cookie alone would leave a valid credential in the hands
    of anyone who had copied it."""
    sign_in(client, account)
    r = client.post("/api/auth/logout")

    assert r.status_code == 200
    assert r.json()["tokens_revoked"] == 1
    live = session.scalar(
        select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked.is_(False))
    )
    assert live == 0


def test_a_logged_out_session_cannot_refresh(client, account):
    raw = refresh_cookie(sign_in(client, account))
    client.post("/api/auth/logout", headers=use_cookie(client, raw))

    assert client.post(
        "/api/auth/refresh", headers=use_cookie(client, raw)
    ).status_code == 401


def test_logout_does_not_need_a_valid_access_token(client, account):
    """A teacher whose access token has already expired must still be able to
    end the session."""
    sign_in(client, account)
    assert client.post("/api/auth/logout").status_code == 200


# --- CSRF ------------------------------------------------------------------
def test_a_cross_origin_refresh_is_refused(client, account):
    """The browser attaches this cookie automatically, so without an Origin
    check any site the teacher visits could mint tokens for themselves."""
    sign_in(client, account)
    r = client.post("/api/auth/refresh", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_an_allowed_origin_still_works(client, account):
    sign_in(client, account)
    r = client.post("/api/auth/refresh", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 200


def test_the_applications_own_origin_is_allowed(client, account):
    """Browsers send Origin on same-origin POSTs too, so a check against the
    allowlist alone rejects the application's own page. The demonstration page
    served from this API was refused for exactly this reason - the allowlist
    held the frontend's port, not its own.
    """
    sign_in(client, account)
    r = client.post(
        "/api/auth/refresh", headers={"Origin": str(client.base_url).rstrip("/")}
    )
    assert r.status_code == 200, r.text
