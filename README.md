# Elimu Analytics

An Item Response Theory-based learning gap detection system for Kenya's Competency-Based Education at the Lower and Upper Primary level.

Abdalla Muhammad Murshid (169962) · Supervisor: Daniel Machanje
Strathmore University, School of Computing and Engineering Sciences

---

## Phase 1 — walking skeleton

This is deliberately the thinnest end-to-end slice: one hardcoded strand, a real `girth` 2-PL calibration, a number on a bare page. No authentication, no database, no styling.

It proves one thing: **the chain connects.** Browser → FastAPI → girth → browser.

### Run it

Windows, from the repo root:

```cmd
tasks setup
tasks run
```

Then open <http://127.0.0.1:8000>.

Other tasks: `tasks test`, `tasks lint`, `tasks fix`, `tasks ci`.
`tasks ci` runs exactly what GitHub Actions runs, before you push.

Manual equivalent, if you prefer:

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements-dev.txt
pytest
cd backend && python -m uvicorn app.main:app --reload --port 8000
```

The venv matters. Three dependency collisions occurred during Phase 0 on a shared global interpreter — a Brotli decoder mismatch that surfaced as a fake connection error, an `h11` downgrade that broke the API client while installing an embedder, and a torch/transformers version conflict. One environment per project makes those impossible.

### What you should see

| Learner | Answered | θ | Tier | Flaggable |
|---|---|---|---|---|
| Chebet K. | 12 | ≈ −1.74 | Below expectation | yes |
| Amina W. | 12 | ≈ 0.65 | Meets expectation | no |
| Otieno J. | 3 | **not shown** | **not shown** | no |

Otieno is the important row. He answered three items, which is below the evidence threshold established in the Phase 0 spike, so the system refuses to estimate his ability at all rather than reporting a confident-looking number derived from noise.

---

## Structure

```
elimu-analytics/
├── .github/workflows/ci.yml    lint + tests on every push
├── spike/                      Phase 0 validation scripts and results
├── data/README.md              data provenance and regeneration
├── docs/SPRINT1.md             sprint evidence
├── pyproject.toml              ruff + pytest config
├── tasks.bat                   task runner
├── backend/
│   ├── app/
│   │   ├── irt.py      girth wrapper - all Phase 0 rules enforced here
│   │   ├── data.py     hardcoded item bank; the seam where PostgreSQL arrives
│   │   └── main.py     FastAPI routes
│   ├── tests/
│   │   └── test_irt.py regression tests for every spike finding
│   └── requirements.txt
└── frontend/
    └── index.html      one page, no build step
```

---

## Phase 0 findings encoded in this code

The spike produced ten amendments. Five of them are structural and are built in from the first commit rather than left as documentation:

| Finding | Where it lives |
|---|---|
| Response matrix must be items × students — `girth` calibrates a transposed matrix silently | `irt.validate_matrix`, `test_matrix_is_items_by_students` |
| Responses must be integer 0/1, not boolean | `irt.validate_matrix`, `test_boolean_responses_rejected` |
| Missing responses are `INVALID_RESPONSE`, never `NaN` | `irt.validate_matrix`, `test_nan_rejected_in_favour_of_invalid_response` |
| No confident θ below 5–10 answered items per strand | `irt.diagnose`, `test_no_theta_below_minimum_responses` |
| Calibrate per strand in batches of 100–300 items | `irt.MAX_ITEMS_PER_CALIBRATION`, `test_batch_size_guard` |

The four rubric tiers are KICD's own wording, taken from the Grade 5 Science & Technology Curriculum Design (Revised 2024), not invented.

Full write-up: `01_HANDOVER/PHASE0_SPIKE_SUMMARY.md` in the project package.

---

## Not yet real

Everything here is a placeholder with a known replacement:

- **Responses** are simulated from known θ values. Phase 2 replaces `data.py` with PostgreSQL.
- **Tier cut points** (−1.0 / 0.0 / 1.0) are provisional and must be set from real class data in Phase 2.
- **Flagging** checks one assessment. The design requires two consecutive below-threshold assessments.
- **No authentication.** Phase 2.
- **No RAG or report generation.** Phase 5 — validated separately in the Day 5 spike.

---

## Next: Phase 2

Database models, JWT authentication, the IRT engine running against PostgreSQL, item bank CRUD, per-strand batch calibration, and the minimum-responses rule applied to real data.
