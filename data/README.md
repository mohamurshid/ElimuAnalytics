# Data

Large datasets are deliberately **not** committed. This file documents what the
project uses, where it comes from, and how to regenerate anything that is missing.

---

## 1. Riiid Answer Correctness Prediction (IRT calibration)

| | |
|---|---|
| Source | Kaggle — *Riiid Answer Correctness Prediction* |
| Size | `train.csv`, 5.5 GB, ~101M rows |
| Used for | Validating 2-PL calibration on real response data (Phase 0, Days 2–3) |
| In repo | No — regenerable, and far over GitHub's file limit |

**Regenerate the working sample:**

```cmd
python spike\sample_by_users.py
```

This produces `riiid_sample_by_users.csv` (~44 MB, 3,000 students, 7,856 items
with at least 30 responses).

**Sample by random user ID, never by row position.** Riiid orders rows by
student, so the first 10,000 rows contain only 21 unique students and zero
items clear the 30-response calibration threshold. This was found by testing
during Phase 0 and is the reason `sample_by_users.py` exists.

---

## 2. KICD curriculum (RAG grounding)

| | |
|---|---|
| Source | KICD Grade 5 Science & Technology Curriculum Design (Revised 2024) |
| URL | `https://cbcelimu.com/wp-content/uploads/2024/12/GRADE.5.SCIENCE.pdf` |
| Extraction | Direct text extraction — **no OCR required** |
| In repo | Yes — `spike/kicd_curriculum_chunks.py` and `.json` (~15 KB) |

Eight chunks across three strands, preserving KICD's structure: Strand →
Sub-strand → Specific Learning Outcomes → Suggested Learning Experiences →
Key Inquiry Questions → Assessment Rubric.

The four-level rubric (Exceeds / Meets / Approaches / Below expectation) is
KICD's own wording and is what the system's ability tiers map onto.

**Note:** Mathematics was not used — that PDF is download-restricted on KICD's
Drive. Same publisher and template, so extractability is proven equally.

---

## 3. Claude API

| | |
|---|---|
| Used for | Curriculum-grounded diagnostic report generation |
| Models | Haiku 4.5 (English), Sonnet 4.5 (Kiswahili) |
| Auth | `ANTHROPIC_API_KEY` environment variable — **never committed** |
| Measured cost | 1.19 cents per bilingual report; ~$2.36 projected for the project |

Verify connectivity:

```cmd
python spike\test_claude_api.py
```

---

## 4. PostgreSQL + pgvector (Phase 2)

Not yet provisioned. Phase 2 introduces a local instance via Docker Compose —
development runs against local Postgres, never cloud RDS. The schema is designed
in Chapter 4, section 4.4.1.
