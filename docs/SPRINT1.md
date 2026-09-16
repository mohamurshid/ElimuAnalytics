# Sprint 1 — Data Preparation & Development Environment Setup

*Abdalla Muhammad Murshid (169962) · Elimu Analytics · Supervisor: Daniel Machanje*

Evidence against each Sprint 1 requirement, with the command that demonstrates it.

---

## 1. A properly set up development environment

| | |
|---|---|
| Language | Python 3.10 (backend), vanilla JS (frontend) |
| Isolation | `venv` per project — `.venv/`, git-ignored |
| Backend | FastAPI + Uvicorn |
| IRT engine | `girth` 0.8.0 (2-PL MMLE + EAP) |
| Dependencies | `backend/requirements.txt` (runtime), `backend/requirements-dev.txt` (adds pytest, httpx, ruff) |

```cmd
tasks setup
tasks run
```

Then <http://127.0.0.1:8000>.

**Why a venv per project, specifically:** three dependency collisions occurred during Phase 0 on a shared global interpreter — a Brotli decoder incompatibility that surfaced as a false connection error, an `h11` downgrade that broke the Claude API client while installing an embedding model, and a torch/transformers version mismatch. Isolation makes those impossible. This is a decision taken from evidence, not convention.

---

## 2. A clean and professionally organised codebase

```
elimu-analytics/
├── .github/workflows/ci.yml    automated lint + test on every push
├── backend/
│   ├── app/
│   │   ├── irt.py              IRT engine; all Phase 0 rules enforced
│   │   ├── data.py             data access seam — PostgreSQL replaces this in Phase 2
│   │   └── main.py             FastAPI routes
│   ├── tests/test_irt.py       9 regression tests
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/index.html
├── spike/                      Phase 0 validation scripts and results
├── data/README.md              data provenance and regeneration
├── docs/SPRINT1.md             this document
├── pyproject.toml              ruff + pytest configuration
├── tasks.bat                   task runner
└── README.md
```

Separation of concerns: the IRT engine knows nothing about HTTP, the routes know nothing about `girth`, and `data.py` is the single seam where the database arrives in Phase 2.

---

## 3. All code maintained using Git version control

```cmd
git log --oneline
git remote -v
```

- Repository initialised at `C:\dev\elimu-analytics`, **deliberately outside OneDrive** — file sync and `.git` corrupt each other
- `.gitignore` excludes the venv, `__pycache__`, `.env`, API keys, and datasets
- **No secret has ever been committed.** The Claude API key lives only in an environment variable
- Remote: GitHub (see repository URL)

---

## 4. Relevant data, databases, APIs and files prepared

Documented in full in `data/README.md`.

| Resource | Status |
|---|---|
| **Riiid dataset** (5.5 GB) | Sampled to 3,000 students / 7,856 usable items via `spike/sample_by_users.py`. Calibration validated |
| **KICD curriculum** | 8 chunks extracted from the official Grade 5 Science & Technology design (Revised 2024). No OCR required. Committed |
| **Claude API** | Key provisioned, connectivity verified, cost measured at 1.19 cents per bilingual report |
| **PostgreSQL + pgvector** | Phase 2. Schema designed in Chapter 4 §4.4.1 |

A non-obvious data finding: sampling Riiid by row position yields 21 unique students and zero usable items, because the file is ordered by student. Sampling by random user ID yields 3,000 students and 7,856 items. This was found by testing rather than assumed, and it is why the sampling script exists as a separate, committed artefact.

---

## 5. Appropriate use of automation

| Automation | What it does |
|---|---|
| **GitHub Actions** (`.github/workflows/ci.yml`) | Lint and full test suite on every push and pull request, against Python 3.10 and 3.12 |
| **pytest suite** (9 tests) | Every test encodes a Phase 0 finding. Three of them guard against errors that produce *wrong numbers rather than exceptions* |
| **ruff** | Linting and import ordering, configured in `pyproject.toml` |
| **`tasks.bat`** | `setup`, `test`, `lint`, `fix`, `run`, `ci` — one command each |
| **`tasks ci`** | Runs locally exactly what CI runs, before pushing |

```cmd
tasks ci
```

### What the tests actually protect

`girth` accepts three malformed inputs without raising, and silently calibrates nonsense. Each now fails loudly, with a test:

| Guard | Test |
|---|---|
| Response matrix must be items × students | `test_matrix_is_items_by_students` |
| Responses must be integer 0/1, not boolean | `test_boolean_responses_rejected` |
| Missing responses are `INVALID_RESPONSE`, never `NaN` | `test_nan_rejected_in_favour_of_invalid_response` |
| No ability estimate below 5 answered items per strand | `test_no_theta_below_minimum_responses` |
| Calibration batches capped at 300 items | `test_batch_size_guard` |

---

## Demonstrable progress this week

Beyond environment setup, a working end-to-end slice exists:

```cmd
tasks run
```

Browser → FastAPI → real `girth` 2-PL calibration → ability estimate on the page.

| Learner | Items answered | θ | KICD tier | Flagged |
|---|---|---|---|---|
| Chebet K. | 12 | −1.74 | Below expectation | yes |
| Amina W. | 12 | 0.65 | Meets expectation | no |
| Otieno J. | 3 | *not shown* | *not shown* | no |

The third row is the point. Otieno answered three items, below the evidence threshold established in Phase 0, so the system refuses to estimate his ability rather than reporting a confident-looking number derived from noise. At one item per learner the correlation between estimated ability and observed performance was 0.380; at ten items it was 0.746.

Chebet's true ability was set to −1.80 in the simulation and `girth` recovered −1.74 from twelve items.

---

## Prior work: Phase 0 technical spike

Before any application code was written, a six-day spike tested the two assumptions the system depends on. Full write-up: `01_HANDOVER/PHASE0_SPIKE_SUMMARY.md` in the project package; scripts in `spike/`.

| Day | Outcome |
|---|---|
| 1 | Synthetic IRT validation — blind parameter recovery at 0.97 / 0.95 / 0.94 |
| 2 | Real data — sampling trap found; calibration timing measured |
| 3 | Validity check — minimum-responses threshold established |
| 4 | KICD curriculum extraction — no OCR needed |
| 5 | RAG spike — 100% retrieval accuracy across three query phrasings; grounded generation verified by verbatim citation |
| 6 | Go/no-go — **GO**, conditional on ten Chapter 3 amendments |

Total API cost of the spike: **$0.03**.

The spike also produced two methodological findings worth noting: in both the Day 3 and Day 5 cases, an apparent model failure turned out to be a flawed measurement. A control arm caught it both times. That experience is why the test suite, rather than the documentation, is where the findings now live.
