# Elimu Analytics - test record

Initial testing and evaluation, started for the progress review of
23 October 2026 and updated 24 October. Three kinds of evidence:

1. **Automated tests** - what the code is checked against on every push.
2. **Functional test record** - features exercised end to end, with the
   expected result, the actual result and the correction made. Most of
   these were found by running the real system (live API calls, the app in a
   phone-width browser), not by reading code.
3. **Evaluation measurements** - figures from instruments that import the
   production code, each with its sample size *n*.

Every correction points at the commit that made it, so it can be inspected.

---

## 1. Automated tests

**472 backend tests** (pytest), plus frontend lint, type check and a
production build. Run locally with `tasks ci` (backend) and `tasks webci`
(frontend); GitHub Actions runs CI on every push. All pass at the time of
writing.

Tests run on an in-memory SQLite database and never call a paid API: the
language model, Google and the sentence embedder are replaced with
stand-ins, so the suite is free, offline and repeatable.

| Suite | Tests | What it holds the system to |
|---|---:|---|
| `test_reporting.py` | 53 | Report generation end to end: pending row, background fill, failures written on the row, stale rows, strand grade used for retrieval |
| `test_reports.py` | 44 | The report prompt: verbatim-citation rule, no gendered pronouns, evidence thresholds, word limit, failure pattern |
| `test_classrooms.py` | 36 | Classes and learners, school scoping, withdraw-not-delete, grade must be exactly "Grade 1"-"Grade 6" |
| `test_curriculum.py` | 31 | Corpus normalisation (PDF glyph repair), curriculum-head cut |
| `test_generation.py` | 26 | AI question writing: drafts only, every server check, near-copies, option shuffle, daily cap, failures |
| `test_grounding.py` | 25 | The grounding checker: verified quotes, fabricated citations, Kiswahili |
| `test_assessments.py` | 24 | Answer submission is idempotent; unknown learners, drafts and withdrawn items refused |
| `test_item_status.py` | 24 | Only approved questions reach a learner's device; no key or mark scheme in what the device receives; review, report, retire, versions |
| `test_catalogue.py` | 22 | Curriculum catalogue built from the real corpus: 448 rows, 427 sub-strands, name cleaning pinned on real text |
| `test_diagnostics.py` | 22 | Heatmap calibrates at most once per strand and not at all once the strand is calibrated, with the same abilities either way; an unanswered question breaks nothing; three states for a cell; the Overview's reported count |
| `test_auth_items.py` | 21 | Passwords hashed, roles, question bank permissions; a teacher's own question with optional misconceptions |
| `test_accounts.py` | 17 | Setup codes (single use, expiry, throttling, one answer for every wrong case); sessions end at once; a school keeps a head teacher |
| `test_google_auth.py` | 17 | Google sign-in: staff list is the gate, linking, state, nonce, each ID-token claim, PKCE, cancellation |
| `test_quizzes.py` | 16 | Quiz selection (spread across difficulty, least-answered first, deterministic), saved quiz sets, numbering after withdrawal |
| `test_refresh.py` | 16 | Rotating refresh tokens, reuse detection, cross-site refusal |
| `test_class_strands.py` | 14 | What a class is assessed on; strands shared across schools; removing keeps every answer |
| `test_export.py` | 14 | PDF export: text extracted and checked, glyph handling |
| `test_repository.py` | 14 | Response matrix rules from Phase 0 (items x students, 0/1, missing not NaN) |
| `test_retrieval.py` | 10 | Retrieval pre-filter and floor |
| `test_login_throttle.py` | 9 | Sign-in throttling by account and address |
| `test_irt.py` | 9 | 2-PL estimation and KICD tier cut-offs |
| `test_calibration.py` | 8 | Strand calibration and flags after two consecutive low results |

---

## 2. Functional test record

| ID | Feature | Expected | Actual (before correction) | Correction | Commit |
|---|---|---|---|---|---|
| F01 | Corpus extraction | Each KICD sub-strand row captured in full | 41% of a row lost where it continued onto the next page; the projects every grounded report quotes were in 0 of 1,617 chunks | Continuation rows attached to their sub-strand (extractor v4), Kiswahili section labels included | c964cfe |
| F02 | Day 5 grounding instrument | Measures the prompt that ships | It held its own drifted copy of the prompt, and overlapping anchors were double-counted | Imports the production prompt; anchors reduced to maximal matches; `--repeat N` | de96cb2, 3789d5e |
| F03 | First live report | Actionable for a teacher, about a learner of unknown gender | Wrong answers referred to by prompt-internal numbers ("items 1, 3, 9"); learner called "she" from the name | Questions named by what they asked; no gendered pronouns, tested | 89e95c5 |
| F04 | Generate a report from the browser | Report appears | "Internal Server Error": generation took 32-38 s and the development proxy gives up at ~30 s; first request also paid a 30.2 s embedder load | Languages generated in parallel (37.8 s -> 26.5 s); embedder warmed at start-up; then fully asynchronous: 202 + polling | 79c634c, 647a3d8, ab67557 |
| F05 | Report failure handling | A failure the teacher can read | A subclass exception was caught by the wrong clause, so a server bug became a 409 | Clauses reordered (79c634c); every failure stored on the report row | 79c634c, dcb8096, e57f183 |
| F06 | Retrieval instrument | Measures what ingest embeds | It embedded whole chunks; ingest embeds the curriculum head only | Imports `embedding_text` from the backend; re-measured | 174851d |
| F07 | PDF export | Test proves the PDF says the right thing | Test checked only the byte size | Text extracted with pdfplumber and checked | 9075c87 |
| F08 | Class grade | Only "Grade 1"-"Grade 6" accepted | "grade 5", "Gr 5", "Grade 7" accepted, silently breaking curriculum lookups | Server-side validation + grade picker | b31fcec |
| F09 | Profile theme | Lint clean | `set-state-in-effect` lint error | Read with `useSyncExternalStore` | 3cdb087 |
| F10 | Curriculum catalogue names | No extraction debris in names | "Uakifishi Vipindi 4)" - caught by the catalogue's own debris test | Lesson-count pattern widened | b335f04 |
| F11 | Strands on the class page | Listed in curriculum order, other grades labelled | 3.3 listed before 3.2; a Grade 4 strand unlabelled; empty strands added 40 "no level yet" cells | Curriculum order; grade label; empty strands kept out of heatmap | 74ac831 |
| F12 | Newly added strand on the quiz page | Visible | Strand with no questions silently hidden - looked lost | Listed, greyed, with the reason | d28ffa0 |
| F13 | AI question generation, live run 1 | Most of 5 questions saved | 0 of 5 saved: misconceptions sent as a list aligned by position; the model put the empty entry first whatever the key's position | Each option carries its own misconception; regression test | 91b6c79 |
| F14 | Generation checks | A suspicious mark scheme is dropped, not repaired | A misconception written on the key was silently blanked - caught by a test | Dropped and recorded with its reason | 91b6c79 |
| F15 | Generation, live run 3 | Fix holds against the real model | 5 of 5 saved, 0 dropped, 0.30 US cents, 44 s | - (confirmation) | 91b6c79 |
| F16 | Strand page (live, phone width) | Correct, current information | A finished run's note shown on every later visit; question text repeated when opened; misconception boxes too small | Note shown only after a run in this visit; text shown once; two-line boxes | 59b16bf |
| F17 | Quiz pages wording | Matches a saved quiz | "already answered this strand"; "This strand has no active items" before any quiz existed | Wording fixed | 59b16bf |
| F18 | Paper quiz after a question is reported | Grid columns match the printed sheet | Columns renumbered after a withdrawal, mismatching the paper | Questions keep their original numbers | 59b16bf |
| F19 | Measurement spike on fake data | Pipeline runs end to end | Near-copy within one run described as "already in the bank" (production wording) | Wording corrected | 3fca358 |
| F20 | Generated key position (measured, n=143) | Roughly 25% each of A-D | Low effort: A 54, B 43, C 31, D 15 | Options shuffled on the server when saved | 562b16e |
| F21 | Generation token limit (measured, n=68) | No request cut off | 1 medium-effort Kiswahili request cut off after 6,638 thinking tokens | Limit raised 8,000 -> 16,000 | 562b16e |
| F22 | Ending sessions | Other devices refused at once | First design compared token times to the whole second, leaving a same-second gap - caught by a test | Session version counter carried in the token | e450199 |
| F23 | Staff page | Lint clean | `set-state-in-effect` lint error | Fetch in the effect, set state on arrival | e450199 |
| F24 | Teacher accounts (live, phone width) | Add -> code -> set up -> sign in; deactivate locks out at once | All as expected: code shown once; loosely typed code accepted; reuse refused; live token refused on deactivation; only head cannot be demoted; sign out everywhere ends a held token | - | e450199 |
| F25 | Google sign-in | Only staff-list emails get in; tampering refused | 17 tests against a stand-in for Google pass. Live, 22 October: the button appears once the credentials are set, and Google accepts the client and redirect address. The full sign-in (turned away, then let in) is still to run | - | 61d456d |
| F26 | Heatmap after a new question is approved (found while testing F27) | Levels still shown | Server error: girth fails on a question nobody has answered, so approving one in a strand the class had already answered took down the heatmap, learner page, Recalibrate and Record levels | Unanswered questions left out of calibration and ability estimates; Recalibrate leaves their parameters empty and says how many. Regression test; checked live (levels shown with 13 questions, 1 unanswered) | f936c0d |
| F27 | Heatmap load time (measured live, 24 October) | A teacher is not kept waiting | 5-7 s reported; profiled: one calibration takes 1-3 s per strand (12-50 questions x 40 learners) and ran on every page load, while estimating abilities takes about 3 ms | Uses the parameters Recalibrate saved; calibrates only when an answered question has none. Live: 1.5 s and 2.9 s before Recalibrate, 60 ms and 122 ms after, same level counts (8 / 12 / 15 / 4). Tested to give identical abilities | f936c0d |
| F28 | Leaving quiz mode on a device (found reading the code) | Every teacher can unlock | Unlocking needed the account password; a teacher who signs in only with Google has none and would be stuck in quiz mode | A 4-digit PIN chosen when the session starts; the password still works if it is forgotten. Live: no PIN refused at start, wrong PIN refused, right PIN returns to the class page | 020e936 |
| F29 | Write your own question (live, phone width) | Saved and usable at once | As expected: empty form, duplicate options and a much-longer key each caught; saved approved with its optional note; "Write another" gives a clean form | - | 020e936 |
| F30 | Mark a paper quiz, one learner at a time (live, phone width) | Marks only open questions; nothing saved until Submit | As expected: earlier answers shown as recorded, Right / Wrong / Blank and Next learner work, Submit bar appears and goes with Clear. Wording fixed: double full stop after a name ending in ".", "1 answer ... keep them", a learner's list status now shows what is left to mark | Wording fixes | 020e936 |
| F31 | Overview, waiting questions (live) | A head teacher sees a reported question without opening its strand | As expected: "1 reported question" with a link to its strand; hidden when nothing waits | - | f936c0d |

---

## 3. Evaluation measurements

Figures from instruments that import the production code. Each figure
carries its sample size; small samples are said to be small.

**Retrieval** (17 October, `spike/retrieval_at_scale.py`)

| Test | n | Result |
|---|---:|---|
| Heading queries over the whole corpus | 300 queries, 1,617 chunks | top-1 46.3%, top-5 72.0%, MRR 0.577 |
| Realistic teacher phrasings | 14 queries | top-1 64.3% unfiltered -> **100% with grade + learning-area pre-filter** |

These are different tests and must not be compared with each other.

**Report grounding** (18 October, `spike/day5_rag_spike_v3.py --repeat 5`)

| Condition | n | Verdicts |
|---|---:|---|
| English, loose prompt | 5 | UNGROUNDED 3, WEAK 2 |
| English, strict verbatim citation (production) | 5 | GROUNDED 5 |
| Kiswahili, Haiku 5.5 / Sonnet 5.5 | 5 each | GROUNDED 5 each |
| Strict + learner's failure pattern | 5 | GROUNDED 5 |

Cost of a bilingual report: 0.35 US cents, about 23 seconds (production,
17 October).

**AI question generation** (21 October, run 20261021_095316,
`spike/generation_at_scale.py`): 34 sub-strands, 2 from each of the 17
grade / learning-area pairs, one 5-question request per setting. Total
cost $0.146.

| | Haiku, low effort | Haiku, medium effort |
|---|---|---|
| Questions passing the server's checks | 84.1% (143/170) | 91.5% (151/165) |
| Requests failed | 0/34 | 1/34 (cut off, see F21) |
| Cost per request | 0.17 US cents | 0.26 US cents |
| Time per request (mean) | 15.2 s | 21.0 s |
| Key is the longest option | 31.5% | 33.8% |
| Kiswahili questions with English words | 0/26 | 0/17 |

**Pending:** whether the keys are *correct* is being judged by hand on a
blind sample of 40 questions (20 per setting), and the near-copy threshold
from 50 labelled pairs (`tasks gen --score 20261021_095316`).

---

## 4. Found by testing, not yet corrected

| Issue | Status |
|---|---|
| Grade 2 Kiswahili and Grade 6 English absent from the corpus | Corpus gaps; listed as unavailable in the catalogue |
| Kiswahili vague-phrase list unvalidated | Needs a Kiswahili speaker |
| Model exceeds the advisory word limit (265 vs 200 before the limit was raised to 250) | Limit advisory; recorded |
| Quiz answers held in memory until submitted | A dropped connection at submission loses them; local draft + retry planned |
| A teacher who signs in only with Google cannot set a password: Change password asks for the current one | Let them set one without it |
| The optional note under each wrong option on the write-a-question screen has no name for a screen reader | Label it |
