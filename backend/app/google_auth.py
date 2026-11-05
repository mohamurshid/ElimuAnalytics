"""
Sign in with Google (OpenID Connect), beside passwords.

Asked for by the supervisor, 21 October. Built on the accounts work of the
same day, which was shaped for it:

  * **The head teacher's staff list is the gate.** Google proves who someone
    is; it says nothing about whether they teach at a school. A Google account
    gets in only if its verified email belongs to a teacher a head teacher has
    added (staff.py), and that account is active. There is no self sign-up.
  * **Linked by Google's id after the first time.** The first sign-in matches
    by email; the Google account's stable `sub` is then stored
    (models.GoogleIdentity) and matched from then on, so changing an email on
    either side neither loses nor misdirects the link. A teacher can link one
    Google account.
  * **Our sessions stay the only sessions.** Google is used once, at sign-in.
    After that the teacher has the same rotating refresh cookie and short
    access tokens as a password sign-in, so sign-out-everywhere, deactivation
    and the session version all apply unchanged.

THE FLOW (authorization code with PKCE)
  /api/auth/google/start     makes a random state, PKCE verifier and nonce,
                             keeps them in a short-lived signed httpOnly
                             cookie, and redirects to Google
  Google                     the teacher chooses an account and agrees
  /api/auth/google/callback  checks the state against the cookie, exchanges
                             the code (with the verifier) for an ID token,
                             checks the token, finds the teacher, issues our
                             session cookie, and returns to the app

CHECKING THE ID TOKEN
The token comes straight from Google's token endpoint over TLS, in exchange
for a code only this server could redeem (it holds the client secret and
the PKCE verifier). OpenID Connect Core 1.0, section 3.1.3.7, allows TLS
server validation in place of checking the token's signature in exactly
that case; the claims are still checked: issuer, audience, expiry, nonce
and a verified email. Recorded as a decision, not an oversight - it also
keeps a cryptography dependency out of a Windows install.

CONFIGURATION (environment variables, never files)
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET   from the Google Cloud console
  GOOGLE_REDIRECT_URI   default http://localhost:3000/api/auth/google/callback
                        - through the frontend's /api proxy, so the session
                        cookie is first-party to the app
  APP_URL               where to send the teacher afterwards, default
                        http://localhost:3000
  PUBLIC_URL            optional second address for the same app, e.g. the
                        tunnel teachers' phones use during UAT (29 October)
Without the first two, the button is not shown and /start says so.

TWO ADDRESSES (29 October)
The laptop is reached as localhost and, by phones, through a tunnel. A
sign-in must come back to the address it started from - the cookies belong
to that address - so /start picks whichever configured address the request
came in on, and the callback uses that same one. Only configured addresses
are ever used: a request naming any other host gets APP_URL, so a forged
Host header cannot send a teacher, or Google's code, anywhere else. Each
address's /api/auth/google/callback must be registered in Google Cloud.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import _issue_refresh
from .db import get_session
from .models import GoogleIdentity, Teacher
from .security import ALGORITHM, COOKIE_SECURE, normalise_email, secret

router = APIRouter(prefix="/api/auth", tags=["auth"])

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
FLOW_COOKIE = "elimu_google"
FLOW_COOKIE_PATH = "/api/auth/google"
FLOW_TTL_SECONDS = 600


def client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "")


def client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "")


def redirect_uri() -> str:
    return os.environ.get(
        "GOOGLE_REDIRECT_URI", "http://localhost:3000/api/auth/google/callback"
    )


def app_url() -> str:
    return os.environ.get("APP_URL", "http://localhost:3000").rstrip("/")


def public_url() -> str:
    return os.environ.get("PUBLIC_URL", "").rstrip("/")


def allowed_origins() -> list[str]:
    return [o for o in (app_url(), public_url()) if o]


def origin_for(request: Request) -> str:
    """The configured address this request came in on, else APP_URL.

    Through the frontend's /api proxy the browser's host arrives as
    X-Forwarded-Host (proxies append, so the first entry is the browser's);
    directly, as Host. Matched against configured addresses only."""
    forwarded = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    for host in (forwarded, request.headers.get("host", "")):
        for origin in allowed_origins():
            if host and urlparse(origin).netloc.lower() == host.lower():
                return origin
    return app_url()


def callback_for(origin: str) -> str:
    """Where Google returns to. APP_URL keeps GOOGLE_REDIRECT_URI, so an
    existing setup is unchanged; another address uses its own callback."""
    if origin == app_url():
        return redirect_uri()
    return f"{origin}/api/auth/google/callback"


def configured() -> bool:
    return bool(client_id() and client_secret())


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _back_to_app(reason: str | None = None, origin: str | None = None) -> RedirectResponse:
    """Return to the app - to sign-in with a reason, or home on success.
    The flow cookie is spent either way."""
    base = origin if origin in allowed_origins() else app_url()
    target = f"{base}/login?google={reason}" if reason else f"{base}/"
    response = RedirectResponse(target, status_code=302)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_COOKIE_PATH)
    return response


def exchange_code(code: str, verifier: str, redirect: str | None = None) -> dict:
    """Redeem the code at Google's token endpoint. Its own function so the
    tests can stand in for Google."""
    reply = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id(),
            "client_secret": client_secret(),
            # Must be the one the browser was sent to Google with.
            "redirect_uri": redirect or redirect_uri(),
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
        timeout=10,
    )
    reply.raise_for_status()
    return reply.json()


def claim_problem(claims: dict, nonce: str, now: float | None = None) -> str | None:
    """Why an ID token's claims cannot be accepted, or None."""
    now = time.time() if now is None else now
    if claims.get("iss") not in ISSUERS:
        return "issuer"
    if claims.get("aud") != client_id():
        return "audience"
    if float(claims.get("exp", 0)) <= now:
        return "expired"
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        return "nonce"
    if claims.get("email_verified") is not True or not claims.get("email"):
        return "unverified email"
    if not claims.get("sub"):
        return "no subject"
    return None


def find_teacher(session: Session, claims: dict) -> tuple[Teacher | None, str | None]:
    """The teacher this Google account signs in as, linking it the first
    time; or None and the reason."""
    linked = session.get(GoogleIdentity, claims["sub"])
    if linked is not None:
        return session.get(Teacher, linked.teacher_id), None

    email = normalise_email(claims["email"])
    teacher = session.scalar(select(Teacher).where(Teacher.email == email))
    if teacher is None:
        return None, "not_registered"
    other = session.scalar(
        select(GoogleIdentity).where(GoogleIdentity.teacher_id == teacher.teacher_id)
    )
    if other is not None:
        return None, "other_google"
    session.add(GoogleIdentity(sub=claims["sub"], teacher_id=teacher.teacher_id,
                               email_at_link=email))
    return teacher, None


@router.get("/providers")
def providers() -> dict:
    """Which sign-in methods to offer. The button is hidden, not broken,
    on a server without Google credentials."""
    return {"password": True, "google": configured()}


@router.get("/google/start")
def google_start(request: Request) -> RedirectResponse:
    origin = origin_for(request)
    if not configured():
        return _back_to_app("not_configured", origin)
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(24)
    query = urlencode({
        "client_id": client_id(),
        "redirect_uri": callback_for(origin),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
        "code_challenge_method": "S256",
        "prompt": "select_account",  # shared phones: always ask which account
    })
    response = RedirectResponse(f"{AUTHORIZE_URL}?{query}", status_code=302)
    flow = jwt.encode(
        {"state": state, "verifier": verifier, "nonce": nonce, "origin": origin,
         "exp": int(time.time()) + FLOW_TTL_SECONDS},
        secret(), algorithm=ALGORITHM,
    )
    # Lax, so it is sent on Google's top-level redirect back to us.
    response.set_cookie(FLOW_COOKIE, flow, httponly=True, secure=COOKIE_SECURE,
                        samesite="lax", path=FLOW_COOKIE_PATH, max_age=FLOW_TTL_SECONDS)
    return response


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    here = origin_for(request)
    if error:
        return _back_to_app("cancelled", here)
    try:
        flow = jwt.decode(request.cookies.get(FLOW_COOKIE, ""), secret(),
                          algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return _back_to_app("expired", here)
    # Signed by this server at /start, so it is the address the flow began on;
    # checked against the configured ones anyway in case the setting changed.
    origin = flow.get("origin") if flow.get("origin") in allowed_origins() else app_url()
    if not state or not code or not hmac.compare_digest(state, flow["state"]):
        return _back_to_app("state", origin)

    try:
        tokens = exchange_code(code, flow["verifier"], callback_for(origin))
        claims = jwt.decode(tokens["id_token"], options={"verify_signature": False})
    except Exception as exc:  # Google refused, or answered with something unusable
        print(f"google sign-in failed: {type(exc).__name__}: {exc}")
        return _back_to_app("google_error", origin)
    if claim_problem(claims, flow["nonce"]) is not None:
        return _back_to_app("invalid", origin)

    teacher, reason = find_teacher(session, claims)
    if teacher is None:
        session.rollback()
        return _back_to_app(reason, origin)
    if not teacher.is_active:
        session.rollback()
        return _back_to_app("deactivated", origin)
    # Google has just proved this email belongs to them, so an unused setup
    # code is no longer needed.
    teacher.setup_code_hash = None
    teacher.setup_code_expires_at = None
    session.commit()

    response = _back_to_app(None, origin)
    _issue_refresh(session, response, teacher, family_id=None)
    return response
