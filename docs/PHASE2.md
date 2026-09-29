# Phase 2 — Backend core

Step 1: schema and persistence. The walking skeleton now reads from PostgreSQL
instead of an in-memory array, and produces the same numbers.

## Run it

```cmd
docker compose up -d
.venv\Scripts\activate
pip install -r backend\requirements.txt
cd backend
python -m app.seed
python -m uvicorn app.main:app --reload --port 8000
```

Then <http://127.0.0.1:8000>. The three learners behave exactly as before —
Chebet at θ ≈ −1.74, Amina at 0.65, Otieno refused for insufficient evidence.
That is the test: **if the numbers move when the database arrives, the database
layer has introduced an error.**

`python -m app.seed --reset` drops everything and reseeds.

## What is here

| File | Purpose |
|---|---|
| `docker-compose.yml` | `pgvector/pgvector:pg16`, port 5432, named volume |
| `backend/app/models.py` | All eleven tables from Chapter 4 §4.4.1 |
| `backend/app/db.py` | Lazy engine, session factory, extension setup |
| `backend/app/repository.py` | Data access — replaces `data.py` |
| `backend/app/seed.py` | Schema creation and demonstration classroom |
| `backend/tests/test_repository.py` | Seven tests, SQLite-backed |
| `alembic.ini`, `backend/alembic/` | Migrations, URL taken from `DATABASE_URL` |

## Schema

Eleven tables as designed: `school`, `teacher`, `classroom`, `student`,
`strand`, `item`, `response`, `ability_score`, `gap_flag`, `report`,
`curriculum_chunk`.

Three deliberate departures from the diagram, each with a reason:

**`ability_score.items_answered`** was added. The Day 3 minimum-responses rule
cannot be enforced downstream without knowing how many items an estimate rests
on. Without this column, a θ computed from two responses is indistinguishable
from one computed from twenty.

**`curriculum_chunk` carries `grade`, `learning_area` and `sub_strand`.**
Retrieval filters on these *before* similarity is considered. Measured at full
corpus scale, realistic queries reach 64.3% top-1 without the filter and 100%
with it, because 26% of KICD sub-strand titles repeat across grades — the
distinguishing information is metadata, not text.

**`response.correctness` stays boolean**, and is converted to integer 0/1 in
`repository.build_response_matrix`. Boolean is the domain truth; girth rejects
booleans. The conversion belongs at the boundary, not in the schema.

## Migrations

The first migration is generated against a running database:

```cmd
docker compose up -d
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

`app.seed` calls `create_all` directly, which is fine for development. Once the
first migration exists, prefer `alembic upgrade head` so that schema changes are
version-controlled rather than implicit.

## Tests

```cmd
tasks test
```

Sixteen tests: nine from Phase 1 guarding the girth contract, seven new ones
guarding the database layer. The new ones assert that:

- the matrix built from SQL is items × students
- it is integer, not boolean, despite the column being boolean
- unanswered items are `INVALID_RESPONSE`, not zero — an unanswered item is not
  a wrong answer, and encoding it as one biases every estimate downward
- the database reproduces the skeleton's θ to within 0.01
- the minimum-responses rule still refuses Otieno
- flagging requires **two consecutive** below-threshold assessments
- a low-evidence estimate never contributes to a flag, however low it looks

They run on SQLite, so the suite needs no Docker and CI stays fast.
`curriculum_chunk` is excluded because pgvector has no SQLite equivalent; it is
exercised in Phase 5.

## Step 2 — calibration, assessment, flagging

| Endpoint | Does |
|---|---|
| `POST /api/strands/{id}/calibrate` | Estimates item parameters, writes them back |
| `POST /api/strands/{id}/assess` | Records an ability estimate per learner, raises flags |
| `GET /api/flags` | The intervention queue |

Run assessment **twice** to see a flag. One below-threshold result is not enough;
the design requires two consecutive, and the first run deliberately raises nothing.

A learner below the minimum-responses threshold gets no recorded estimate at
all, so they can never accumulate a flag however many cycles run.

**Performance note.** `assess_strand` originally called `diagnose` per learner,
and each call recalibrated the strand - forty calibrations per assessment. The
test suite took 97 seconds for a twelve-item strand. Calibration is a property
of the strand, not the learner, so it now happens once and the EAP step is
vectorised across the class: **97 seconds to 5.9**. At 400 items per strand that
is the difference between usable and unusable.

## Step 3 — authentication and the item bank

Login takes JSON, not an OAuth2 form, which keeps the dependency list to PyJWT
and bcrypt.

```
POST /api/auth/login   {"email": "...", "password": "..."}  -> bearer token
GET  /api/auth/me      current account
GET  /api/items        list (any authenticated account)
POST /api/items        create
PATCH /api/items/{id}  edit wording, activate or deactivate
DELETE /api/items/{id} school_admin or above
```

Seeded demonstration accounts, both with password `elimu-demo`:

| Email | Role |
|---|---|
| `teacher@example.school` | teacher |
| `head@example.school` | school_admin |

Roles are ranked rather than compared for equality, so a check reads "at least
school_admin" and adding a role later does not mean revisiting every endpoint.
The token carries the role, but every request resolves it back to the database
row - a role changed by an administrator takes effect on the next request rather
than when the token expires.

### Two safeguards on the item bank

**An answered item cannot be rewritten.** Editing the wording of a question
learners have already answered turns their responses into answers to a question
that no longer exists. The API returns 409 and suggests deactivating the item
and creating a replacement.

**An answered item is never deleted.** The foreign key cascades, so deleting it
would remove the responses with it and silently change every ability estimate
ever derived from them. Such an item is deactivated instead: withdrawn from
future calibration, history intact. Only an item nobody has answered is deleted
outright, and the response tells you which happened.

### `JWT_SECRET`

There is a development default so the project runs out of the box, and the
application prints a warning at startup when it is in use. Set `JWT_SECRET`
before any deployment - a default signing key is not a weak secret, it is a
published one.

## Step 4 — login throttling

`POST /api/auth/login` was unlimited. bcrypt is deliberately slow, so guessing
one password online was already expensive, but an unthrottled endpoint still
allows thousands of attempts overnight against a weak password - and these
accounts hold children's assessment records.

`app/throttle.py` refuses a key holding five failures inside fifteen minutes
and answers **429** with a `Retry-After` header. It is a sliding window rather
than a lockout timer: failures age out on their own, so nothing has to schedule
an unlock.

Four decisions, each closing a way throttles usually go wrong:

**Keyed by account *and* source address.** Keying on the address alone would
lock out a whole school sharing one connection. Keying on the account alone
would let anyone deny a named teacher access by failing five logins against
their address. The pair means an attacker throttles only themselves.

**Checked before the password, not after.** Verifying first and waiving the
limit on success would let through exactly the attempt that matters - the
attacker's correct guess. A correct password is refused while throttled.

**`X-Forwarded-For` is ignored unless `TRUST_PROXY_HEADER` is set.** That header
comes from the client. Trusting it by default would let an attacker send a new
address each attempt and never be throttled at all. Turn it on deliberately,
behind a proxy that sets it.

**Stale keys are swept.** Otherwise an attacker cycling addresses grows the
counter dictionary without bound.

Two limits, stated rather than hidden: the state is in-process, so it is lost
on restart and N workers mean N times the allowance - acceptable on a single
instance, not acceptable behind a load balancer, where it belongs in Redis. And
it raises the cost of an attack rather than stopping one, since an attacker with
many source addresses gets an allowance per address.

Tunable by environment: `LOGIN_MAX_ATTEMPTS`, `LOGIN_WINDOW_SECONDS`,
`TRUST_PROXY_HEADER`.

Nine tests cover it, including window expiry with an advanced clock rather than
a real sleep, and isolation between accounts and between addresses.

## Step 5 — lifespan handler

`@app.on_event("startup")` is deprecated in FastAPI. The development-secret
warning now runs inside an `asynccontextmanager` passed as `lifespan=`, which
removes four deprecation warnings from the test run and leaves a place for
shutdown work to go later.

## Still to do in Phase 2

- Classroom and student CRUD (teachers currently come from the seed)
- Row-level scoping on those endpoints, so a teacher cannot read another
  school's learners - the first place children's data crosses a trust boundary
- Refresh tokens, if session length becomes a usability problem in UAT
