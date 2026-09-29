"""
Login throttling.

bcrypt is deliberately slow, so guessing one password online is already
expensive. It is not impossible: an unthrottled endpoint still allows thousands
of attempts overnight against a weak password, and teacher accounts hold
children's assessment records. This module caps the rate.

A sliding window, not a lockout timer. A key is refused while it holds
MAX_ATTEMPTS failures inside the last WINDOW_SECONDS; as those failures age out
the allowance returns on its own. Nothing has to schedule an unlock.

Three decisions worth defending:

**Keyed by account *and* source address.** Keying on the address alone would
lock out a whole school sharing one connection. Keying on the account alone
would let anyone deny service to a named teacher by failing five logins against
their address. The pair means an attacker throttles only themselves, and a
teacher locked out from one place can still sign in from another.

**A correct password is refused while a key is throttled.** Checking the
password first and waiving the limit on success would defeat the purpose: an
attacker's final, correct guess is exactly the one that must not be allowed
through.

**`X-Forwarded-For` is ignored unless TRUST_PROXY_HEADER is set.** That header
is supplied by the client. Trusting it by default would let an attacker send a
different value each attempt and never be throttled at all. Behind a reverse
proxy that sets it, turn it on deliberately.

Known limits, stated rather than hidden:

- State is in-process. It is lost on restart, and N worker processes mean N
  times the allowance. That is acceptable for a single-instance deployment and
  is not acceptable behind a load balancer, where this belongs in Redis.
- It throttles per source address, so an attacker with many addresses gets an
  allowance per address. It raises the cost of an attack; it does not stop one.
"""

from __future__ import annotations

import os
import threading
import time

MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
WINDOW_SECONDS = int(os.environ.get("LOGIN_WINDOW_SECONDS", "900"))  # 15 minutes
TRUST_PROXY_HEADER = os.environ.get("TRUST_PROXY_HEADER", "").lower() in {"1", "true", "yes"}

# How often stale keys are swept out, so that an attacker cycling through
# addresses cannot grow this dictionary without bound.
_SWEEP_EVERY_SECONDS = 60

_failures: dict[tuple[str, str], list[float]] = {}
_lock = threading.Lock()
_last_sweep = 0.0


def _now() -> float:
    """Indirection so tests can advance the clock without sleeping."""
    return time.monotonic()


def client_address(request) -> str:
    """The source address to throttle on.

    `request.client` is None for some transports (ASGI test clients, unix
    sockets), so it falls back to a constant rather than raising - one shared
    bucket is a safer failure than no throttling at all.
    """
    if TRUST_PROXY_HEADER:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # The left-most entry is the original client; the rest are proxies.
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def key_for(email: str, request) -> tuple[str, str]:
    return (email.strip().lower(), client_address(request))


def _prune(key: tuple[str, str], now: float) -> list[float]:
    cutoff = now - WINDOW_SECONDS
    kept = [t for t in _failures.get(key, []) if t > cutoff]
    if kept:
        _failures[key] = kept
    else:
        _failures.pop(key, None)
    return kept


def _sweep(now: float) -> None:
    global _last_sweep
    if now - _last_sweep < _SWEEP_EVERY_SECONDS:
        return
    _last_sweep = now
    cutoff = now - WINDOW_SECONDS
    for key in list(_failures):
        kept = [t for t in _failures[key] if t > cutoff]
        if kept:
            _failures[key] = kept
        else:
            del _failures[key]


def retry_after(key: tuple[str, str]) -> int | None:
    """Seconds until this key may try again, or None if it may try now."""
    now = _now()
    with _lock:
        _sweep(now)
        attempts = _prune(key, now)
        if len(attempts) < MAX_ATTEMPTS:
            return None
        # Freed when the oldest failure in the window ages out.
        return max(1, int(attempts[0] + WINDOW_SECONDS - now) + 1)


def record_failure(key: tuple[str, str]) -> None:
    now = _now()
    with _lock:
        _prune(key, now)
        _failures.setdefault(key, []).append(now)


def clear(key: tuple[str, str]) -> None:
    """Called on a successful sign-in: the account is not under attack."""
    with _lock:
        _failures.pop(key, None)


def reset() -> None:
    """Drop all state. For tests, and for an administrator clearing a lockout."""
    global _last_sweep
    with _lock:
        _failures.clear()
        _last_sweep = 0.0
