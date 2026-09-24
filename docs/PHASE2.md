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

## Still to do in Phase 2

- Classroom and student CRUD (teachers currently come from the seed)
- Rate limiting on login
- Refresh tokens, if session length becomes a usability problem in UAT
