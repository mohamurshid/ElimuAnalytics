# Elimu Analytics

An Item Response Theory-based learning gap detection system for Kenya's
Competency-Based Education, Upper Primary (Grades 4-6).

Abdalla Muhammad Murshid (169962) · Supervisor: Daniel Machanje
Strathmore University, School of Computing and Engineering Sciences

A teacher picks the KICD sub-strands a class is working on. AI drafts
multiple-choice questions from that sub-strand's official curriculum text; a
teacher reviews and approves them. Learners answer on the teacher's phone, or
on paper that the teacher marks. A 2-PL IRT model estimates each learner's
ability per strand, and a learner below expectation in two consecutive
assessments joins the support list. For any learner, the system writes a
bilingual (English and Kiswahili) diagnostic report grounded in verbatim KICD
curriculum text, exported as a PDF for parents.

---

## Status - 23 October 2026

| Area | State |
|---|---|
| IRT engine (2-PL, girth), calibration per strand, two-consecutive-low flag | Complete |
| Classes, learners, school scoping, roles (teacher / head teacher) | Complete |
| KICD curriculum corpus in pgvector; grade + learning-area filtered retrieval | Complete |
| Bilingual grounded reports, verbatim-citation check, PDF export | Complete |
| Curriculum catalogue (Grades 4-6, six learning areas) and per-class strand picker | Complete |
| AI question generation, server-side checks, teacher review, versions, reporting a question | Complete; measured (see `docs/TEST_RECORD.md`) |
| Quizzes of a set length - on the device, or on paper with a printable sheet | Complete |
| Teacher accounts: head teacher adds staff, one-time setup codes, change password, sign out everywhere | Complete |
| Sign in with Google (OpenID Connect), gated by the staff list | Complete; live test needs Google credentials |
| Offline answer queue, cloud deployment | Not started - see Limitations |

**472 backend tests**, frontend lint + type check + production build, CI on
every push. Evidence of testing and evaluation: **`docs/TEST_RECORD.md`**.

---

## Run it

Windows `cmd`, from the repository root. Requires Python 3.12, Node 20+ and
Docker Desktop.

### Once

```cmd
tasks setup                             venv + Python dependencies
cd frontend && npm install && cd ..     frontend dependencies
docker compose up -d                    PostgreSQL 16 + pgvector
```

Secrets are environment variables, set once with `setx` in a new terminal,
**never written to a file or committed**. Close and reopen the terminal after.

| Variable | Needed for | Required? |
|---|---|---|
| `ANTHROPIC_API_KEY` | Reports and AI question writing | For those features |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Sign in with Google | Optional; the button is hidden without them |
| `JWT_SECRET` | Signing sessions | Has a development default; set it before any deployment |

Google sign-in needs a Google Cloud OAuth client (Web application) with the
redirect URI `http://localhost:3000/api/auth/google/callback`, and the
consent screen in Testing mode with your accounts added as test users.

### Each time the schema changes, and before a demonstration

```cmd
tasks seed --reset                      drop and rebuild schema + demonstration data
tasks ingest                            load the KICD corpus (1,617 chunks; a few minutes)
```

`--reset` deletes everything in the local database. Without it, `tasks seed`
only creates tables that are missing.

### To use it

```cmd
tasks run                               backend, http://127.0.0.1:8000  (API docs at /docs)
tasks web                               frontend, http://localhost:3000 (second terminal)
```

Demonstration accounts, password `elimu-demo` (published - change them
before any real use):

| Email | Role |
|---|---|
| `teacher@example.school` | Teacher |
| `head@example.school` | Head teacher |

A head teacher adds real teachers at **Profile -> Manage teachers**. Each new
teacher gets a one-time setup code, shown once, and sets their own password
at **Set up your account** on the sign-in page - or uses **Continue with
Google** if the head teacher added their Google email.

### Other tasks

| Task | Does |
|---|---|
| `tasks ci` | Lint + the backend test suite - exactly what GitHub Actions runs |
| `tasks webci` | Frontend lint, type check and production build (stop `tasks web` first) |
| `tasks gen` | Question-generation measurement: plan only; `--go` calls the API (~$0.20) |
| `tasks test`, `tasks lint`, `tasks fix` | Parts of the above |
| `tasks check`, `tasks query` | Retrieval checks against the loaded corpus |

The test suite uses SQLite and stand-ins for every paid or external service,
so it needs no Docker, no API key and no network.

**Use the `tasks` targets rather than calling Python directly.** Each one
activates the virtual environment first. Without it the commands run against
the system interpreter and fail with `No module named 'girth'`, which names a
package rather than the cause and looks exactly like a broken install.
`docs/RUNBOOK.md` has the expected output of every step and the four failure
modes that actually occur.

**The venv matters.** Three dependency collisions occurred during Phase 0 on a
shared global interpreter — a Brotli decoder mismatch that surfaced as a fake
connection error, an `h11` downgrade that broke the API client while installing
an embedding model, and a torch/transformers version conflict. One environment
per project makes those impossible.

---

## The core workflow, to demonstrate

1. Sign in as `head@example.school`. **Classes -> Grade 5 Blue.**
2. **Add a strand** - Grade 5 -> Science and Technology -> 3.2 Sound Energy.
3. On the strand's **Questions** page, **Write 5 questions**. About 40
   seconds; the server checks every question and saves the ones that pass as
   drafts.
4. **Review questions** - one at a time: the key, why it is right, what each
   wrong option suggests, the curriculum line it came from. Approve, edit or
   reject.
5. **Give a quiz** - *On this device* with 5 questions, or *Mark paper quiz*
   with a printable question sheet.
6. **Record levels** twice -> learners below expectation twice appear on
   **Support**.
7. Open a learner -> **Generate report** -> English and Kiswahili, each
   quoting the KICD curriculum verbatim -> **Download PDF**.

The seeded Heat Transfer strand already has twelve answered questions, so
steps 6-7 work on it straight away. Chebet K. is the learner below
expectation; Otieno J. answered only three questions, so the system refuses
to estimate his level rather than guess.

---

## Technologies

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic |
| Database | PostgreSQL 16 + pgvector (Docker) |
| IRT | `girth` (2-PL, marginal maximum likelihood), NumPy, SciPy |
| Retrieval | sentence-transformers `all-MiniLM-L6-v2`, cosine distance in pgvector, metadata pre-filter |
| Language model | Anthropic Claude Haiku 5.5 - reports and question drafting, structured output for questions |
| PDF | ReportLab (bundled Vera fonts) |
| Auth | bcrypt, short-lived JWT access tokens, rotating httpOnly refresh cookies, OpenID Connect (Google) |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4 |
| Quality | pytest, ruff, ESLint, GitHub Actions |

---

## Structure

```
elimu-analytics/
├── .github/workflows/ci.yml    lint + tests on every push
├── docker-compose.yml          pgvector/pgvector:pg16
├── tasks.bat                   task runner (see above)
├── backend/app/
│   ├── main.py                 app, routers, start-up warm-up
│   ├── models.py               the schema
│   ├── irt.py, calibration.py  2-PL estimation, calibration, flags
│   ├── repository.py           queries; builds the response matrix
│   ├── classrooms.py           classes and learners
│   ├── catalogue.py            KICD curriculum catalogue (Grades 4-6)
│   ├── class_strands.py        what a class is assessed on
│   ├── items.py, item_status.py   question bank, review, versions
│   ├── questions.py            question-writing prompt and checks (pure)
│   ├── generation.py           AI question writing (async), daily cap
│   ├── quizzes.py              quizzes of a set length, saved sets
│   ├── assessments.py          answer submission (idempotent), device quiz
│   ├── diagnostics.py          heatmap, learner levels, support list
│   ├── retrieval.py, curriculum.py, ingest_curriculum.py   corpus + RAG
│   ├── reports.py, reporting.py, grounding.py, export.py   reports + PDF
│   ├── auth.py, security.py, staff.py, google_auth.py, throttle.py   accounts
│   └── seed.py                 demonstration data
├── backend/tests/              472 tests
├── frontend/                   Next.js app: app/, components/, lib/
├── spike/                      measurement instruments and their results
├── data/kicd/                  harvested curriculum corpus + coverage report
└── docs/
    ├── TEST_RECORD.md          tests, functional record, measurements
    ├── ARCHITECTURE.md         how it fits together
    └── RUNBOOK.md              start-up, expected output, failure modes
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

`data/kicd/` holds the KICD rationalised curriculum designs (Revised 2024),
harvested by `spike/build_curriculum_corpus.py`: **1,617 curriculum
sub-strand chunks** across Grades 1-6, plus **924 assessment rubric rows**.
The source PDFs are not committed (110 MB, regenerable - see
`data/README.md`).

Retrieval is filtered by grade and learning area before similarity is
considered, and that filter is not an optimisation: KICD's curriculum is
spiral, so sub-strand titles repeat across grades. Measured on 14 realistic
teacher phrasings, top-1 accuracy is 64.3% over the whole corpus and 100%
with the filter (n=14 - a small sample).

---

## Limitations

- **No offline queue.** Quiz answers are held on the device until the teacher
  submits; the server is already idempotent, so a queue is frontend work.
- **Not deployed.** Teachers using their own phones need a public HTTPS
  address; Google sign-in then needs that address as a redirect URI.
- **Grades 4-6 only** for the catalogue and question writing. Grade 6 English
  and Grade 2 Kiswahili are missing from the corpus (extraction gaps).
- **Simulated demonstration responses.** Generated from known abilities, so
  estimates can be checked against the truth; real classroom data has none.
- Known problems and their consequences are listed in `docs/TEST_RECORD.md`
  section 4.
