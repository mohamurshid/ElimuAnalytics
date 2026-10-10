# Phase 2.5 — the API the interface needs

Phase 2 produced a working backend. Checking what a frontend would actually
call revealed that it was shaped for a demonstration rather than for a user
interface, in six specific ways. Building Phase 3 against it would have meant
rewriting Phase 3 later, so this step closed the gaps first.

---

## What was missing

| Gap | Consequence |
|---|---|
| Nothing recorded a response | Only `seed.py` ever created a `response` row. A quiz interface had nothing to submit to |
| `/api/diagnose/{id}` used `strands[0]` | Invisible with one strand, wrong with six |
| No strand list | Strands were reachable only inside `/api/health` |
| `/api/learners` returned three learners | It filters to the named demonstration learners |
| No class-wide diagnostics | A heatmap of forty learners across six strands was 240 requests |
| `/api/flags` was unscoped and unauthenticated | It returned every open flag in the database, from every school |

A seventh, found while checking: **the plain HTML page had been partly broken
since authentication landed in Phase 2 Step 3.** Its Calibrate and Run
assessment buttons sent no `Authorization` header, so both had been answering
401. It is fixed here.

---

## `POST /api/assessments`

The endpoint a quiz interface submits to, and in Phase 4 the endpoint a tablet
drains its offline queue into. Both uses shaped it.

```json
{
  "client_batch_id": "9f1c…",
  "class_id": "…",
  "strand_id": "…",
  "responses": [
    {"student_id": "…", "item_id": "…", "correct": true}
  ]
}
```

**A batch, not one response per request.** Forty learners × twelve items is
480 rows. Sent individually over a weak connection that is 480 chances to
half-fail; sent as one batch it either lands or it does not.

**The client supplies the identifier.** A device that submits and then loses
the connection before the reply arrives does not know whether the work was
recorded, so it retries. The server cannot tell that retry from a genuine
second submission — they are byte-identical. Only the device knows, so the
device generates `client_batch_id` once and resends it unchanged on every
attempt.

That identifier is `UNIQUE` in the database, so a duplicate is caught by a
constraint rather than by a check-then-insert that two concurrent retries
could both pass. A duplicate is answered **200 with `duplicate: true`**, not an
error: the device did nothing wrong and the outcome it wanted has already
happened. Answering 4xx would make a correct client look broken.

### Four rejections, each a silent-wrong-number risk

| Rejected | Status | Why |
|---|---|---|
| Re-answering an item | 409 | The matrix holds one cell per learner-item pair. A second answer overwrites the first and changes estimates derived from it |
| The same pair twice in one batch | 422 | Same overwrite, within a single request |
| A withdrawn item | 422 | It is outside the calibration pool, so the response would be stored and never counted |
| A learner from another classroom | 422 | |

Validation runs over the whole batch before anything is written. A partly
recorded batch is the worst outcome available: the device cannot safely retry
it and the data is half there. A test asserts that a rejected batch leaves
zero rows behind, including the batch record itself.

`GET /api/assessments/{client_batch_id}` lets a device that lost the reply ask
whether its work landed before deciding to resend.

### Schema

One new table, `assessment_batch`, which the Chapter 4 diagram does not
contain. Idempotency needs somewhere to remember what has already been
accepted. `response.batch_id` is nullable, so seeded responses and anything
recorded before batching existed remain valid.

---

## Read endpoints for the interface

```
GET /api/strands                            name, level, active and calibrated item counts
GET /api/students/{id}/diagnostics          every strand, or ?strand_id= for one
GET /api/classrooms/{id}/heatmap            every learner against every strand, one request
GET /api/flags                              the intervention queue, scoped to the caller's school
```

**Three states, not two.** Every diagnostic cell carries a `status` of
`estimated`, `provisional` or `insufficient_evidence`, with the message
explaining it. A learner below the evidence threshold must be a *reported*
state rather than an absent one: a blank cell reads as a rendering fault when
it is in fact the system declining to guess.

**The heatmap calibrates once per strand, not once per learner.** This is the
Phase 2 performance finding applied to a read path — the earlier version of
that mistake ran forty calibrations per assessment and took the test suite
from 5.9 seconds to 97. A read path hit every time a teacher opens the
dashboard would be worse. A test asserts the call count directly rather than
timing it, because a timing test is flaky on shared hardware.

**`/api/flags` is now authenticated and school-scoped**, consistent with every
other endpoint. It previously returned every open flag in the database, which
was invisible with one school and a disclosure with two.

---

## The Phase 1 endpoints

`/api/learners` and `/api/diagnose/{id}` are marked deprecated in the OpenAPI
schema and left working, so the plain HTML page keeps running. Phase 3 should
call the endpoints above instead. They can be deleted when that page is
replaced.

---

## The demonstration page

`frontend/index.html` gained a sign-in strip. The token is held in a
JavaScript variable and never persisted, so a reload signs you out — the same
choice made for the Phase 3 frontend, and visible here in miniature.

Sign in as `head@example.school` / `elimu-demo` before using Calibrate, Run
assessment or Intervention queue.

---

## Tests

**95 total, 26 new.** Twelve for assessment recording, fourteen for
diagnostics. The ones worth knowing:

- the same batch submitted twice records once, and the second call is a 200
- a rejected batch leaves no rows at all, batch record included
- a recorded response actually changes the response matrix cell from the
  missing-value sentinel to an integer 1
- Otieno comes back as `insufficient_evidence` with the threshold in the
  message, not as a null
- the heatmap calls `calibrate` exactly once for a forty-learner class
- another school's flags, learners, classrooms and heatmaps are all 404 or absent

---

---

## Refresh tokens

The Phase 3 frontend holds its access token **in memory only**. Anything in
`localStorage` is readable by any script that gets injected into the page, so
an XSS flaw there becomes full account takeover. Memory is not readable that
way - but it does not survive a page reload, which would sign a teacher out
every time they refreshed.

So there are two tokens with different jobs:

| | Access token | Refresh token |
|---|---|---|
| Form | JWT, in the response body | Opaque random string, in an httpOnly cookie |
| Held by | JavaScript, in memory | The browser; script cannot read it |
| Life | 15 minutes | 14 days |
| Revocable | No | Yes - stored server-side |
| Used for | Every API call | Nothing but minting access tokens |

The split exists because the two requirements conflict. A credential the page
can read is a credential an injected script can steal; a credential the page
cannot read cannot be attached to ordinary API calls. So the readable one is
made short-lived and disposable, and the durable one is locked away and used
for nothing else.

### Four decisions

**Opaque, not a JWT.** A JWT is valid until it expires and cannot be
withdrawn. Revocability is the entire reason this token is separate from the
access token, so it has to be one the server looks up.

**Stored as a SHA-256 hash, not bcrypt.** The token is 256 bits from the OS
entropy pool, not a guessable password, so there is nothing for a slow hash to
defend against - and the lookup runs on every refresh against an indexed
column. A database disclosure yields nothing usable either way.

**Rotation with reuse detection.** Each refresh issues a new token and retires
the old one. If a retired token is presented again, either the client replayed
it or someone else holds a copy, and the server cannot tell which - so the
whole family is revoked. That turns a stolen refresh token from indefinite
access into one extra session that ends the moment the real teacher next
refreshes, and the forced sign-in is a signal they can notice.

**CSRF: `SameSite` plus an `Origin` check.** The browser attaches this cookie
automatically, so without protection any site the teacher visits could mint
tokens. `SameSite=Lax` is enough while the interface and the API share a
registrable domain - including two ports on localhost. A cross-site deployment
has to weaken it to `none`, and then the `Origin` check is doing the work
alone, which is why both exist. `Origin` is set by the browser and cannot be
forged by page script.

The application's own origin always passes the check, computed from the
request rather than configured. Browsers send `Origin` on **same-origin**
POSTs as well as cross-origin ones, so a check against a configured allowlist
alone refuses the application's own page unless that page's address happens to
be listed. This project fell into exactly that: the demonstration page served
from the API on port 8000 was refused because the allowlist held only the
frontend's port 3000, and the page reported "not signed in" after every
reload. It is self-evidently not CSRF for a page to call its own API, and
requiring each deployment to remember to allowlist itself is a trap.

### Endpoints

```
POST /api/auth/login     sets the cookie, returns a 15-minute access token
POST /api/auth/refresh   rotates the cookie, returns a new access token
POST /api/auth/logout    revokes the family; needs no access token
```

Logout deliberately takes no access token: a teacher whose access token has
already expired must still be able to end the session, and the cookie is the
thing being revoked.

Configurable by environment: `JWT_TTL_MINUTES`, `REFRESH_TTL_DAYS`,
`COOKIE_SECURE`, `COOKIE_SAMESITE`, `ALLOWED_ORIGINS`. `COOKIE_SECURE` must be
on wherever HTTPS is available and off in local development, or the browser
silently drops the cookie.

### Tests

Fifteen. The four that carry the design:

- the cookie is **httpOnly** - if it is not, the whole design is pointless
- refreshing **rotates**, and the spent token is marked revoked
- **replaying a spent token revokes every token in the family**, leaving none live
- **logout revokes server-side** rather than merely clearing the cookie, which
  would leave a valid credential with anyone who had copied it

Plus expiry, forged cookies, cross-origin refusal, and the fact that the
refresh token never appears in a response body.

**A note on how these tests send cookies.** They set an explicit `Cookie`
header over an emptied jar rather than using `client.cookies.set()`. That
method *adds* a cookie instead of replacing one when the domain or path
differ, so a test that plants a forged value ends up with two cookies of the
same name and sends whichever the jar happens to order first - which differs
between httpx versions. Two of these tests passed in one environment and
failed in another for exactly that reason, while the server behaved
identically in both. An explicit header depends on nothing version-specific.

### The demonstration page

`frontend/index.html` now calls `/api/auth/refresh` on load. Sign in, reload,
and you stay signed in - the access token died with the page and was replaced
from the cookie without the page ever being able to read it.
