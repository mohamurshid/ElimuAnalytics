# Elimu Analytics

An Item Response Theory-based learning gap detection system for Kenya's
Competency-Based Education at the Lower and Upper Primary level.

Abdalla Muhammad Murshid (169962) · Supervisor: Daniel Machanje
Strathmore University, School of Computing and Engineering Sciences

Teachers administer offline quizzes on Android tablets. A 2-PL IRT model
estimates each learner's latent ability per CBE strand. Learners falling below
threshold for two consecutive assessments are flagged. The Claude API, grounded
in KICD curriculum via RAG, generates personalised diagnostic reports in English
and Kiswahili.

---

## Status

| Phase | State |
|---|---|
| **0 — Technical spike** | Complete. Decision: GO |
| **1 — Walking skeleton** | Complete |
| **2 — Backend core** | Persistence, calibration, auth and item bank done; classroom/student CRUD outstanding |
| 3 — Frontend | Not started |
| 4 — Offline sync | Not started |
| 5 — RAG + reports | Not started (retrieval validated in Phase 0) |

**42 tests**, lint clean, CI on every push.

---

## Run it

Windows, from the repo root. Requires Docker Desktop.

```cmd
tasks setup                             venv + dependencies
docker compose up -d                    PostgreSQL 16 + pgvector
cd backend
python -m app.seed --reset              schema + demonstration data
python -m uvicorn app.main:app --reload --port 8000
```

- <http://127.0.0.1:8000> — the page
- <http://127.0.0.1:8000/docs> — interactive API: login, item bank, calibration

Demonstration accounts, password `elimu-demo`:

| Email | Role |
|---|---|
| `teacher@example.school` | teacher |
| `head@example.school` | school_admin |

Other tasks: `tasks test`, `tasks lint`, `tasks fix`, `tasks ci`.
`tasks ci` runs exactly what GitHub Actions runs, before you push. The test
suite uses SQLite, so it needs no Docker.

**The venv matters.** Three dependency collisions occurred during Phase 0 on a
shared global interpreter — a Brotli decoder mismatch that surfaced as a fake
connection error, an `h11` downgrade that broke the API client while installing
an embedding model, and a torch/transformers version conflict. One environment
per project makes those impossible.

---

## What you should see

| Learner | Answered | θ | Tier | Flaggable |
|---|---|---|---|---|
| Chebet K. | 12 | ≈ −1.74 | Below expectation | yes |
| Amina W. | 12 | ≈ 0.65 | Meets expectation | no |
| Otieno J. | 3 | **not shown** | **not shown** | no |

Otieno is the important row. He answered three items, below the evidence
threshold established in Phase 0, so the system refuses to estimate his ability
rather than reporting a confident-looking number derived from noise.

These are the same figures the Phase 1 in-memory version produced. They did not
move when PostgreSQL arrived, which is the point: Chebet's true ability was set
to −1.80 in the simulation and `girth` recovers −1.74 from twelve items.

Click **Run assessment** twice, then **Intervention queue**. The first run
raises nothing — the design requires two consecutive below-threshold
assessments. Otieno never appears, however many cycles run.

---

## Structure

```
elimu-analytics/
├── .github/workflows/ci.yml    lint + tests on every push, Python 3.10 and 3.12
├── docker-compose.yml          pgvector/pgvector:pg16
├── alembic.ini                 migrations, URL from DATABASE_URL
├── pyproject.toml              ruff + pytest config
├── tasks.bat                   task runner
├── backend/
│   ├── app/
│   │   ├── main.py             FastAPI routes
│   │   ├── db.py               lazy engine, sessions, extensions
│   │   ├── models.py           eleven tables, from Chapter 4 §4.4.1
│   │   ├── repository.py       all queries; builds the response matrix
│   │   ├── irt.py              girth wrapper; every Phase 0 rule lives here
│   │   ├── calibration.py      strand calibration, assessment, flagging
│   │   ├── security.py         bcrypt, JWT, role ranking
│   │   ├── auth.py             login, current_teacher, require_role
│   │   ├── items.py            item bank CRUD and its safeguards
│   │   └── seed.py             schema creation + demonstration classroom
│   ├── alembic/                migration environment
│   └── tests/                  42 tests, SQLite-backed
├── frontend/index.html         one page, no build step
├── spike/                      Phase 0 scripts, results and transcripts
├── data/
│   ├── README.md               data provenance and regeneration
│   └── kicd/                   harvested curriculum corpus + coverage report
└── docs/
    ├── ARCHITECTURE.md         how it all works — start here
    ├── PHASE2.md               backend build notes
    └── SPRINT1.md              sprint evidence
```

---

## Phase 0 findings encoded in this code

The spike produced ten amendments. Six are structural and are enforced in code
with a test each, rather than documented and trusted. Three of them cause
**wrong numbers rather than errors** when violated.

| Finding | Where it lives |
|---|---|
| Response matrix must be items × students — `girth` calibrates a transposed matrix silently | `irt.validate_matrix`, `repository.build_response_matrix` |
| Responses must be integer 0/1, not boolean | `repository.build_response_matrix` |
| Missing responses are `INVALID_RESPONSE`, never `NaN` | `irt.validate_matrix` |
| No θ below 5 answered items, no confidence below 10 | `irt.diagnose` |
| Calibrate per strand in batches of ≤ 300 items | `irt.MAX_ITEMS_PER_CALIBRATION`, `calibration.calibrate_strand` |
| Flag only after two consecutive below-threshold assessments | `calibration.assess_strand` |

The four rubric tiers are KICD's own wording, from the Grade 5 Science &
Technology Curriculum Design (Revised 2024), not invented.

Full write-up: `01_HANDOVER/PHASE0_SPIKE_SUMMARY.md` in the project package.

---

## Curriculum corpus

`data/kicd/` holds the KICD rationalised curriculum designs (Revised 2024)
harvested by `spike/build_curriculum_corpus.py`: **68 documents across all six
primary grades and every learning area**, yielding **1,617 curriculum sub-strand
chunks** plus **923 assessment rubric rows**, deduplicated and structure-aware.

Retrieval was measured at that scale by `spike/retrieval_at_scale.py`:

| Condition | Top-1 |
|---|---|
| Realistic queries, whole corpus | 64.3% |
| Same queries, filtered by grade + learning area | **100%** |

The reason is structural. 26% of KICD sub-strand titles repeat across grades —
78% in Mathematics — because the curriculum is deliberately spiral. The
information that separates Grade 3 *Length* from Grade 5 *Length* is not in the
text, it is metadata. So filtering by grade and learning area before embedding
is required, not an optimisation. `curriculum_chunk` carries those columns for
exactly this reason.

The source PDFs are not committed (110 MB, regenerable — see `data/README.md`).

---

## Item bank safeguards

Two behaviours worth knowing before you use the API.

**An answered item cannot be rewritten.** Editing the wording of a question
learners have already answered turns their responses into answers to a question
that no longer exists. The API returns 409 and suggests deactivating and
replacing it.

**An answered item is never deleted.** The foreign key cascades, so deleting it
would take those responses with it and silently change every ability estimate
derived from them. Such an item is deactivated instead — withdrawn from future
calibration, history intact. Only an item nobody has answered is deleted
outright, and the response tells you which happened.

---

## Not yet real

| Real | Placeholder |
|---|---|
| IRT engine and every rule around it | Learner responses (simulated from known abilities) |
| Database schema, migrations | Tier cut points (−1.0 / 0.0 / 1.0), to be set from real class data |
| Authentication, hashing, role enforcement | Demonstration accounts and passwords |
| Item bank and its safeguards | Twelve Heat Transfer questions |
| Flagging logic | — |
| Curriculum corpus, harvested and validated | Not yet loaded into `curriculum_chunk` |

Simulated responses are a deliberate choice, not a shortcut: because the true
abilities are known, the estimates can be checked against them. Real SBA data
has no ground truth to check against.

`JWT_SECRET` has a development default so the project runs out of the box, and
the app warns at startup when it is in use. Set it before any deployment.

---

## Next

**Phase 2 remainder** — classroom and student CRUD, login rate limiting.

**Phase 3** — React/Next.js frontend: dashboard, competency heatmap,
intervention queue, quiz interface, built against this backend rather than mocks.

**Phase 4** — IndexedDB caching and sync.

**Phase 5** — RAG pipeline: embed the corpus into `curriculum_chunk`, retrieve
with the grade-and-learning-area filter, generate bilingual reports with the
strict citation prompt, export PDFs.

See `docs/ARCHITECTURE.md` for how the current system works.
