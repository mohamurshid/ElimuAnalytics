# How Elimu Analytics works

A walkthrough of the system as it stands: what each part does, how a request
travels through it, and why each non-obvious decision was made that way.

Written to be read top to bottom once, then used as a reference.

---

## 1. What exists today

A FastAPI backend, a PostgreSQL database with pgvector, a 2-PL IRT engine, JWT
authentication with three roles, an item bank with CRUD, and a deliberately
plain HTML page that exercises it all.

What does **not** exist yet: the React/Next.js frontend, offline sync, and the
RAG report generator. Those are Phases 3, 4 and 5. The RAG half has been
separately validated — see `PHASE0_SPIKE_SUMMARY.md` — but no application code
for it exists.

```
browser  ──HTTP──>  FastAPI  ──SQLAlchemy──>  PostgreSQL
                       │
                       └──> girth (2-PL IRT: calibration + EAP)
```

---

## 2. Follow one request

Click a learner's name on the page and this happens.

**1. The browser** calls `GET /api/diagnose/{student_id}`.

**2. `main.py`** receives it. FastAPI injects a database session through
`Depends(get_session)`. The route looks up the first strand, parses the learner
id, and calls the repository. It contains no IRT logic and no SQL — its whole
job is translating HTTP into domain calls and domain errors into status codes.

**3. `repository.py`** builds the response matrix. This is the load-bearing
step. It queries the active items in the strand and the learners in the class,
then fills an **items × students** array:

```python
matrix = np.full((len(items), len(students)), INVALID_RESPONSE, dtype=int)
...
matrix[r, c] = 1 if correct else 0
```

Three Phase 0 rules are enforced in those two lines. The orientation is items ×
students, because `girth` silently calibrates a transposed matrix and returns
plausible nonsense. The values are integers, because `girth` rejects booleans —
even though the database column is boolean, which is the right domain type. And
unanswered cells hold `INVALID_RESPONSE`, not zero, because an unanswered item
is not a wrong answer and encoding it as one biases every estimate downward.

**4. `irt.py`** validates the matrix, calibrates the strand with 2-PL MMLE, and
estimates the learner's ability with EAP. Then it applies the Day 3 rule:

```python
if answered < MIN_RESPONSES:      # 5
    return {"theta": None, "tier": None, "flaggable": False, ...}
```

Below five answered items the learner gets no number at all. Between five and
ten they get one marked provisional. This is the single most important line in
the system: at one response per learner the correlation between estimated
ability and observed performance was 0.380 — noise — and at ten it was 0.746.

**5. Back up the stack** the θ becomes a KICD tier (`tier_for`), and the route
returns JSON. The page renders it.

Nothing in that path knows about HTTP except `main.py`, and nothing knows about
SQL except `repository.py`.

---

## 3. Module map

| File | Responsibility | Knows about |
|---|---|---|
| `app/main.py` | HTTP routes, status codes | FastAPI, the other modules |
| `app/db.py` | Engine, sessions, extensions | SQLAlchemy |
| `app/models.py` | The eleven tables | SQLAlchemy, pgvector |
| `app/repository.py` | All queries, matrix construction | SQLAlchemy, numpy, girth |
| `app/irt.py` | Calibration, ability, tiers, the rules | numpy, girth |
| `app/calibration.py` | Strand calibration, assessment, flagging | repository, irt |
| `app/security.py` | bcrypt, JWT, role ranking | bcrypt, PyJWT |
| `app/auth.py` | Login, `current_teacher`, `require_role` | security, models |
| `app/items.py` | Item bank CRUD and its safeguards | models, auth |
| `app/seed.py` | Schema creation, demonstration data | everything |

`app/data.py` is the Phase 1 in-memory item bank. Nothing imports it any more;
it is kept only because `test_irt.py` still uses its fixtures.

---

## 4. The five rules, and where each one lives

Every one of these came from testing during Phase 0, and three of them cause
**wrong numbers rather than errors** when violated. That is why each is enforced
in code and pinned by a test, rather than written down in Chapter 3 and trusted.

| Rule | Enforced in | Test |
|---|---|---|
| Matrix is items × students | `irt.validate_matrix`, `repository.build_response_matrix` | `test_matrix_is_items_by_students` |
| Responses are integer 0/1 | `repository.build_response_matrix` | `test_matrix_is_integer_not_boolean` |
| Missing is `INVALID_RESPONSE`, not NaN | `repository.build_response_matrix` | `test_unanswered_items_use_sentinel_not_zero` |
| No θ below 5 answered items | `irt.diagnose` | `test_minimum_responses_rule_survives_the_database` |
| Calibrate ≤ 300 items per batch | `irt.validate_matrix`, `calibration.calibrate_strand` | `test_batch_ceiling_is_enforced` |

And one rule that came from the design rather than the spike:

| Rule | Enforced in | Test |
|---|---|---|
| Flag only after **two consecutive** low assessments | `calibration.assess_strand`, `repository.consecutive_low_assessments` | `test_two_consecutive_assessments_raise_a_flag` |

---

## 5. Decisions worth being able to defend

**Why a repository layer instead of queries in the routes.** The response matrix
has three invariants that are easy to break and impossible to notice. Building
it in exactly one place means those invariants have exactly one home. It also
made the Phase 1 → Phase 2 transition a file swap: `data.py` and `repository.py`
expose the same shape, so no caller changed.

**Why calibration is a separate operation.** Phase 1 calibrated on every request
and threw the parameters away. Day 2 measured calibration cost rising
non-linearly with item count — 8.3s for 100 items, 16.8s for 200, 90.1s for 400.
Recalculating per request does not survive a real item bank, so item parameters
are now estimated deliberately and persisted.

**Why assessment calibrates once for the whole class.** The first version called
`diagnose` per learner, and each call recalibrated the strand: forty calibrations
per assessment. The test suite took 97 seconds on a twelve-item strand.
Calibration is a property of the strand, not of the learner. Fixing that took it
to 5.9 seconds.

**Why roles are ranked, not compared.** `role_at_least(role, ROLE_SCHOOL_ADMIN)`
rather than `role == "school_admin"`. Adding a role later does not mean auditing
every endpoint.

**Why the token is re-resolved on every request.** The JWT carries the role, but
each request loads the `Teacher` row and uses that. An administrator demoting
someone takes effect immediately rather than whenever the old token expires.

**Why an answered item can never be deleted or rewritten.** Deleting cascades to
its responses, which changes every ability estimate ever derived from them.
Rewriting turns existing responses into answers to a question that no longer
exists. Neither failure raises an error — both quietly move the numbers. So an
answered item is deactivated instead, and a rewrite returns 409.

**Why the database engine is lazy.** It was created at import time, which meant
importing any module required a working PostgreSQL driver and URL. The test
suite could not run a single assertion. Now nothing touches the database until
something asks for a session, and the tests run on SQLite.

**Why `ability_score.items_answered` exists** though it is not in the Chapter 4
diagram. Without it, a θ computed from two responses is indistinguishable from
one computed from twenty, and the minimum-responses rule cannot be enforced
downstream. The schema had to change to make the rule enforceable.

---

## 6. What is real and what is placeholder

| Real | Placeholder |
|---|---|
| The IRT engine, and every rule around it | Learner responses (simulated from known abilities) |
| The database schema | Tier cut points (−1.0 / 0.0 / 1.0, to be set from real class data) |
| Authentication, hashing, role enforcement | Demonstration accounts and passwords |
| The item bank and its safeguards | Twelve Heat Transfer questions |
| Flagging logic | — |
| 2,540-chunk curriculum corpus (harvested, validated) | Not yet loaded into `curriculum_chunk` |

The simulated responses are deliberate and useful: Chebet's true ability was set
to −1.80 and `girth` recovers −1.74 from twelve items. Because the truth is
known, the system can be checked against it. Real SBA data has no ground truth
to check against.

---

## 7. How this maps to your objectives

| Objective | Where it is evidenced |
|---|---|
| iii — design the system | Chapter 4 diagrams; `models.py` implements the schema directly |
| iv — develop and implement | Working backend, 42 tests, CI on every push |
| v — test and validate | The test suite; Phase 0 spike results; retrieval measured at scale |

For Chapter 5, the three things worth writing up are the girth contract
findings, the minimum-responses rule with its correlation curve, and the
retrieval pre-filter result (64.3% unfiltered → 100% filtered, because 26% of
KICD sub-strand titles repeat across grades).

---

## 8. Running everything

```cmd
docker compose up -d                    start PostgreSQL + pgvector
cd backend
python -m app.seed --reset              schema + demonstration data
python -m uvicorn app.main:app --reload
```

- <http://127.0.0.1:8000> — the page
- <http://127.0.0.1:8000/docs> — interactive API, where login and the item bank live

```cmd
tasks test     42 tests, SQLite, no Docker needed
tasks lint     ruff
tasks ci       both, exactly what GitHub Actions runs
```

Demonstration accounts, password `elimu-demo`: `teacher@example.school`
(teacher) and `head@example.school` (school_admin).

---

## 9. What comes next

**Phase 2 remainder** — classroom and student CRUD, login rate limiting.

**Phase 3** — the React/Next.js frontend: dashboard, competency heatmap,
intervention queue, quiz interface, built against this backend rather than mocks.

**Phase 4** — IndexedDB caching and sync.

**Phase 5** — the RAG pipeline: embed the curriculum corpus into
`curriculum_chunk`, retrieve with the grade-and-learning-area filter, generate
bilingual reports with the strict citation prompt, export PDFs.
