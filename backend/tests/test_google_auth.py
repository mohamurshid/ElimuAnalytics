"""
Sign in with Google.

Google is always a stand-in here: `exchange_code` is replaced, and the ID
token is built by the test. What is under test is everything this server
decides - which is all of the security: the state and nonce, the claims,
and above all that a Google account gets in only as a teacher a head
teacher has added.
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from app import google_auth
from app.db import get_session
from app.main import app
from app.models import GoogleIdentity, Teacher
from app.security import hash_password
from fastapi.testclient import TestClient
from sqlalchemy import select

from .test_repository import session  # noqa: F401 - pytest fixture

CLIENT_ID = "test-client.apps.googleusercontent.com"


@pytest.fixture
def google(monkeypatch):
    """Configured, with a stand-in for Google's token endpoint."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    reply: dict = {"claims": {}, "fail": False}

    def exchange(code, verifier):
        if reply["fail"]:
            raise RuntimeError("google said no")
        reply["verifier"] = verifier
        return {"id_token": jwt.encode(reply["claims"], "irrelevant", algorithm="HS256")}

    monkeypatch.setattr(google_auth, "exchange_code", exchange)
    return reply


@pytest.fixture
def client(session):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def teacher(session) -> Teacher:  # noqa: F811
    t = session.scalar(select(Teacher))
    t.email = "wanjiru@gmail.com"
    session.commit()
    return t


def claims(issued_nonce: str, /, **change) -> dict:
    base = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "google-123",
            "email": "Wanjiru@gmail.com", "email_verified": True, "nonce": issued_nonce,
            "exp": int(time.time()) + 300}
    return {**base, **change}


def start(client):
    r = client.get("/api/auth/google/start", follow_redirects=False)
    query = parse_qs(urlparse(r.headers["location"]).query)
    return r, {k: v[0] for k, v in query.items()}


def sign_in(client, google, **change):
    """The whole round trip; returns where the app was sent."""
    _r, q = start(client)
    google["claims"] = claims(q["nonce"], **change)
    r = client.get("/api/auth/google/callback", params={"code": "c", "state": q["state"]},
                   follow_redirects=False)
    return r.headers["location"]


# --- offering it -----------------------------------------------------------
def test_the_button_is_offered_only_when_configured(client, google, monkeypatch):
    assert client.get("/api/auth/providers").json()["google"] is True
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    assert client.get("/api/auth/providers").json()["google"] is False
    r = client.get("/api/auth/google/start", follow_redirects=False)
    assert r.headers["location"].endswith("/login?google=not_configured")


def test_start_sends_the_browser_to_google_with_pkce_state_and_nonce(client, google):
    r, q = start(client)
    assert r.status_code == 302
    assert r.headers["location"].startswith(google_auth.AUTHORIZE_URL)
    assert q["client_id"] == CLIENT_ID
    assert q["code_challenge_method"] == "S256" and q["code_challenge"]
    assert q["state"] and q["nonce"] and "openid" in q["scope"]
    cookie = r.headers["set-cookie"]
    assert google_auth.FLOW_COOKIE in cookie and "HttpOnly" in cookie


# --- getting in --------------------------------------------------------------
def test_a_teacher_the_head_added_signs_in_and_is_linked(client, session, google):  # noqa: F811
    t = teacher(session)
    t.setup_code_hash = hash_password("ABCD2345")  # a code they never needed
    session.commit()

    assert sign_in(client, google).endswith("/")
    session.expire_all()
    link = session.get(GoogleIdentity, "google-123")
    assert link is not None and link.teacher_id == t.teacher_id
    assert session.get(Teacher, t.teacher_id).setup_code_hash is None
    # Our own session, exactly as after a password sign-in.
    r = client.post("/api/auth/refresh")
    assert r.status_code == 200 and r.json()["name"] == t.name


def test_once_linked_the_google_id_is_matched_not_the_email(client, session, google):  # noqa: F811
    t = teacher(session)
    sign_in(client, google)
    t.email = "w.kamau@school.ke"  # the head teacher changes it later
    session.commit()
    assert sign_in(client, google, email="wanjiru@gmail.com").endswith("/")


def test_a_google_account_nobody_added_is_turned_away(client, session, google):  # noqa: F811
    assert sign_in(client, google, email="stranger@gmail.com").endswith(
        "/login?google=not_registered")
    assert session.scalar(select(GoogleIdentity)) is None


def test_a_deactivated_teacher_is_turned_away(client, session, google):  # noqa: F811
    t = teacher(session)
    t.is_active = False
    session.commit()
    assert sign_in(client, google).endswith("/login?google=deactivated")


def test_a_teacher_links_only_one_google_account(client, session, google):  # noqa: F811
    t = teacher(session)
    session.add(GoogleIdentity(sub="another-google", teacher_id=t.teacher_id,
                               email_at_link=t.email))
    session.commit()
    assert sign_in(client, google).endswith("/login?google=other_google")


# --- what is refused ------------------------------------------------------------
@pytest.mark.parametrize("change", [
    {"email_verified": False},
    {"aud": "someone-elses-app"},
    {"iss": "https://evil.example"},
    {"exp": int(time.time()) - 5},
    {"nonce": "replayed"},
])
def test_a_token_with_the_wrong_claims_is_refused(client, session, google, change):  # noqa: F811
    teacher(session)
    assert sign_in(client, google, **change).endswith("/login?google=invalid")


def test_a_forged_state_is_refused(client, session, google):  # noqa: F811
    teacher(session)
    start(client)
    r = client.get("/api/auth/google/callback", params={"code": "c", "state": "forged"},
                   follow_redirects=False)
    assert r.headers["location"].endswith("/login?google=state")


def test_a_callback_without_the_flow_cookie_is_refused(client, session, google):  # noqa: F811
    r = client.get("/api/auth/google/callback", params={"code": "c", "state": "x"},
                   follow_redirects=False)
    assert r.headers["location"].endswith("/login?google=expired")


def test_cancelling_at_google_returns_to_sign_in(client, google):
    r = client.get("/api/auth/google/callback", params={"error": "access_denied"},
                   follow_redirects=False)
    assert r.headers["location"].endswith("/login?google=cancelled")


def test_google_refusing_the_code_is_reported(client, session, google):  # noqa: F811
    teacher(session)
    google["fail"] = True
    assert sign_in(client, google).endswith("/login?google=google_error")


def test_the_pkce_verifier_sent_to_google_matches_the_challenge(client, session, google):  # noqa: F811
    import base64
    import hashlib

    teacher(session)
    _r, q = start(client)
    google["claims"] = claims(q["nonce"])
    client.get("/api/auth/google/callback", params={"code": "c", "state": q["state"]},
               follow_redirects=False)
    digest = hashlib.sha256(google["verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == q["code_challenge"]
