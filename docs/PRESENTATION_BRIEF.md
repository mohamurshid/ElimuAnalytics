# Presentation brief

Everything you need to present Elimu Analytics confidently, in the order you
should learn it. Read section 1 twice, run the demo in section 5 three times,
and skim the rest.

---

## 0. The night before, and the morning of

**Tonight, in this order:**

| Do this |
|---|
| Read sections 1–4 once, without notes |
| Get the system running (section 5) and click through the demo twice |
| Re-read sections 2 and 3 **out loud**. These are what you'll be questioned on |
| Run the demo again, narrating as if presenting. Time it |
| Answer every question in section 7 aloud, without looking |
| Skim section 8 (numbers), then **stop**. Don't cram new material late |
| **Run `python -m app.seed --reset` and close everything** — see below |

**Rehearsing contaminates the demo.** Each `Run assessment` click is recorded.
If you rehearse the two-consecutive-assessment moment tonight and don't reset,
tomorrow Chebet is *already* flagged, the intervention queue isn't empty, and
the most persuasive thirty seconds of your demo silently doesn't happen. So the
last thing you do tonight, and again tomorrow before you walk in, is:

```cmd
cd /d C:\dev\elimu-analytics\backend
python -m app.seed --reset
```

**Tomorrow morning, the pre-flight (do this before anyone is watching):**

1. Start Docker Desktop. Wait for it to say running
2. `docker compose up -d`, wait ten seconds
3. `python -m app.seed --reset` from `backend`
4. Start uvicorn
5. Open `http://127.0.0.1:8000` — confirm three learners appear
6. Open `http://127.0.0.1:8000/docs` in a second tab
7. Run `tasks ci` **now**, and leave the passing output in a spare terminal

Do **not** log in to `/docs` during pre-flight. Tokens last 60 minutes; if you
authorize while setting up and then sit through two other presentations, your
token expires and Step 3 dies with a 401 in front of the room. Log in during
the demo, as part of the demo.

---

## 1. The pitch

**One sentence:** Elimu Analytics turns the assessment data Kenyan primary
teachers already collect into per-learner, per-strand diagnostic insight.

**One paragraph, memorise this:**

> Kenya's Competency-Based Education mandates continuous School-Based
> Assessment, but teachers managing 50 to 70 learners have no tool to turn that
> data into diagnosis. Data is collected and never processed. Elimu Analytics
> applies Item Response Theory — the same psychometric method behind PISA,
> TIMSS and Kenya's own KPSEA — to estimate each learner's true ability per
> curriculum strand, flags learners who fall below threshold in two consecutive
> assessments, and uses the Claude API grounded in official KICD curriculum to
> generate a report for the teacher in English and Kiswahili.

**Why it matters:** the World Bank reports most Kenyan children cannot read and
understand an age-appropriate text by age ten. Without early, specific
identification, teachers fall back on generalised intervention.

---

## 2. The one technical idea you must understand

Two learners each score 6 out of 10.

- Learner A got the **six hardest** questions right.
- Learner B got the **six easiest** questions right.

The percentage score says they are identical. They obviously are not.

**Item Response Theory separates how hard a question is from how able a learner
is.** It estimates both at once, from the pattern of who got what right.

The learner's ability comes out as a number called **theta (θ)**:

```
θ = −3        very low ability
θ =  0        average
θ = +3        very high ability
```

In this project θ is estimated **per strand**, not overall — a learner can be
strong in Number and weak in Measurement, and a single score hides that.

θ is then mapped to KICD's four levels — **Exceeds / Meets / Approaches / Below
expectation** — which are KICD's own words, taken from the curriculum design,
not invented.

That is the core. If you understand only this, you can present.

---

## 3. The model, in plain language

It is called a **two-parameter logistic model**, or **2-PL**. Two parameters
because each question has two numbers attached:

| Parameter | Plain meaning |
|---|---|
| **Difficulty (b)** | How hard the question is — the ability level at which a learner has a 50/50 chance |
| **Discrimination (a)** | How well the question separates strong from weak learners. A good question is answered by most strong learners and few weak ones. A bad question is answered at random — those get excluded |

The model says: the probability you answer a question correctly depends on the
gap between your ability and the question's difficulty, sharpened by how
discriminating the question is.

If someone wants the formula:

```
P(correct) = 1 / (1 + e^( −a × (θ − b) ))
```

You do not need to derive it. You need to say what the letters mean.

### Two steps, two names

| What happens | IRT name | When |
|---|---|---|
| Work out each question's difficulty and discrimination, from how a class answered | **Calibration** | Once per strand, after a quiz |
| Work out one learner's ability, from their answers and those question parameters | **Scoring** | Every assessment |

Calibration uses **MMLE** (Marginal Maximum Likelihood Estimation). Say it like
this: *"it estimates the question parameters while averaging over the
distribution of learner abilities, which keeps the estimates unbiased even with
a class-sized sample rather than thousands of learners."*

Scoring uses **EAP** (Expected A Posteriori). Say it like this: *"it's the
average of the plausible ability values given the learner's answers. We chose it
over maximum likelihood because maximum likelihood gives infinite estimates for
a learner who got everything right or everything wrong."*

### It is not a neural network

If asked "what kind of ML model" — it is a **statistical latent-variable
model**, not deep learning. There is no training loop, no loss curve, no epochs.
It is fitted by maximum likelihood. This is the correct and standard method for
educational measurement; PISA and TIMSS use the same family. Saying so is a
strength, not an apology.

---

## 4. The rest of the system, in plain language

**The database (PostgreSQL).** Eleven tables — schools, teachers, classrooms,
students, strands, items, responses, ability scores, gap flags, reports,
curriculum chunks. Standard relational design, matching the Chapter 4 schema.

**pgvector.** A PostgreSQL extension that lets the same database store
"embeddings". Chosen so there is no second database to run and keep in sync.

**Embeddings.** Text turned into a list of numbers such that similar meanings
end up close together. It lets "why does a metal spoon get hot?" find the Heat
Transfer curriculum section even though they share almost no words. The model
used is `all-MiniLM-L6-v2`; it runs on a normal laptop, no GPU.

**RAG — Retrieval-Augmented Generation.** Rather than asking the AI to write a
report from memory, the system first *retrieves* the relevant official KICD
curriculum text, then hands it to the model and requires it to quote from it.
Closed-book versus open-book. It is what stops the system inventing advice.

**JWT authentication.** After you log in, the server gives you a signed token.
You attach it to every request afterwards. Like a wristband checked at the gate,
then shown at each stage. Passwords are stored hashed with **bcrypt** — a
one-way scramble, so even someone reading the database cannot recover them.

**FastAPI.** The Python web framework serving the API. It generates the
interactive documentation page at `/docs` automatically.

**Docker Compose.** Runs PostgreSQL in a container, so the database is identical
on any machine — yours, your supervisor's, an examiner's.

---

## 5. The demo — exactly what to do and say

Set up before you present:

```cmd
cd /d C:\dev\elimu-analytics
docker compose up -d
.venv\Scripts\activate
cd backend
python -m app.seed --reset
python -m uvicorn app.main:app --reload --port 8000
```

Have two browser tabs open: `http://127.0.0.1:8000` and
`http://127.0.0.1:8000/docs`.

### Step 1 — the three learners (tab 1)

Click **Chebet K.**

> "This is a real 2-PL calibration running against PostgreSQL. Chebet answered
> twelve items. Her estimated ability is −1.74, which maps to Below expectation
> on the KICD rubric, and she is flaggable."

Click **Amina W.**

> "Same twelve items, ability 0.65, Meets expectation. Not flagged."

Click **Otieno J.** — **this is the moment of the demo.**

> "Otieno answered three items. The system shows no ability estimate at all and
> no tier. That is deliberate. During technical validation I measured the
> correlation between estimated ability and observed performance at different
> response counts: it was 0.380 at one item, 0.700 at five, 0.746 at ten. Below
> about five items the estimate is noise. So rather than display a
> confident-looking number, the system refuses. Flagging a child on noise would
> put them into an intervention queue they don't belong in."

That single behaviour demonstrates psychometric literacy better than any
feature you could show.

### Step 2 — the two-consecutive rule

Click **Run assessment**.

> "That records an ability estimate for every learner in the strand."

Click **Intervention queue**.

> "Empty. One below-threshold result is not enough."

Click **Run assessment** again, then **Intervention queue** again.

> "Now Chebet appears. The design requires two consecutive below-threshold
> assessments before a learner is flagged, so a single bad day doesn't trigger
> intervention. Otieno still never appears, because he never had a valid
> estimate to begin with."

### Step 3 — roles and safeguards (tab 2, `/docs`)

`POST /api/auth/login` with `teacher@example.school` / `elimu-demo`. Copy the
token, click **Authorize**, paste.

`GET /api/items` →

> "Twelve items, each with a response count."

`DELETE /api/items/{id}` →

> "403. A teacher cannot withdraw items — that's a school administrator action,
> because it changes what every future calibration is computed from."

Log in as `head@example.school`, re-authorize, delete the same item →

> "Even as an administrator it isn't deleted — it's deactivated. The item has
> learner responses attached. Deleting it would cascade and remove those
> responses, which would silently change every ability estimate ever derived
> from them. So it's withdrawn from future calibration and the history is kept."

### Step 3b — login throttling (ten seconds, same tab)

Call `POST /api/auth/login` six times with a wrong password.

> "Six failed sign-ins and it stops answering — 429, with a Retry-After header
> saying when to come back. Two decisions in there. It's keyed by account *and*
> source address, because keying on address alone would lock out a whole school
> sharing one connection, and keying on account alone would let anyone lock a
> named teacher out of her own account. And the limit is checked *before* the
> password is verified, so even the correct password is refused while throttled
> — otherwise you'd wave through exactly the attempt that matters, the
> attacker's successful guess."

If asked whether that's production-ready, say no, and say why before they do:
the counter is in-process, so it's lost on restart and N workers mean N times
the allowance. Fine on one instance, wrong behind a load balancer, where it
belongs in Redis. Naming your own limit is the difference between a considered
decision and an oversight.

### Step 4 — the engineering (terminal)

Show the `tasks ci` output you ran during pre-flight. **Don't run it live** — it
takes about 77 seconds, which is an extremely long silence in front of a room.

> "Lint plus 51 tests. These aren't testing that the IRT library works —
> they're testing that this codebase cannot reintroduce the mistakes I found
> during the technical spike. Three of those mistakes produce wrong numbers
> rather than errors, which is exactly why they're automated rather than
> remembered."

If someone notices the suite is slow: the nine login-throttle tests do real
bcrypt hashing, and bcrypt is deliberately slow. That's the mechanism working,
not a performance problem.

Then show the GitHub Actions tab: green runs on every push, Python 3.10 and 3.12.

---

## 6. What is real and what is a placeholder

Be upfront about this. Volunteering it reads as rigour; being caught reads badly.

| Real | Placeholder |
|---|---|
| The IRT engine and every rule around it | Learner responses, simulated from known abilities |
| The database schema and migrations | Tier cut points (−1.0 / 0.0 / 1.0) |
| Authentication, hashing, role enforcement | Demonstration accounts |
| Item bank and its safeguards | Twelve Heat Transfer questions |
| The curriculum corpus — 1,617 chunks, all six grades | Not yet loaded into the database |

**Why simulated data is a strength, not a shortcut:** Chebet's true ability was
set to −1.80 before any data was generated, and the model recovers −1.74 from
twelve items. Because the truth is known, the estimate can be checked against
it. Real SBA data has no ground truth to check against, so it could not
demonstrate correctness.

---

## 7. Questions you will be asked

**"Why IRT and not just percentage scores?"**
Percentages treat all questions as equal. Two learners scoring 6/10 can have
very different ability if one answered the harder items. IRT separates item
difficulty from learner ability and estimates both. It's the standard for
PISA, TIMSS and KPSEA.

**"Why 2-PL and not 3-PL?"**
3-PL adds a guessing parameter, which needs substantially more data to estimate
stably. With class-sized samples, 2-PL is the defensible choice.

**"Did you train a model?"**
I fitted a 2-PL IRT model by marginal maximum likelihood. It's a statistical
latent-variable model, not a neural network — there's no training loop or loss
curve. I also use a pretrained sentence-embedding model for curriculum retrieval
and a hosted LLM for report generation; neither is fine-tuned.

**"How do you know the IRT model works?"**
Two ways. On synthetic data with known parameters it recovered difficulty at
0.97, discrimination at 0.95 and ability at 0.94. On real data — the Riiid
dataset, 100 million interactions — item difficulty correlated −0.627 with
observed pass rates, which is the right sign and strength.

**"Why does one learner show no result?"**
Deliberate. Below five answered items the estimate is noise. The
ability-versus-performance correlation was 0.380 at one response and 0.746 at
ten. Displaying a number there would be worse than displaying nothing.

**"What happens if the AI makes something up?"**
Three defences. Retrieval is filtered by grade and learning area before
similarity, so the wrong curriculum rarely reaches the model. The prompt
requires the recommended activity to be quoted verbatim from the retrieved text.
And I tested the failure case directly: given deliberately wrong curriculum, the
model refused and asked for the correct section rather than inventing one.

**"How accurate is the retrieval?"**
Measured across 1,617 curriculum chunks spanning six grades: 64.3% top-1
unfiltered, 100% when filtered by grade and learning area. The reason is
structural — 26% of KICD sub-strand titles repeat across grades, 78% in
Mathematics, because the curriculum is deliberately spiral. What distinguishes
Grade 3 Length from Grade 5 Length isn't in the text, it's metadata. So
filtering is required, not an optimisation.

**"Why Kiswahili on a different model?"**
I compared them. The cheaper model produced terminology unfit for classroom use
— it rendered "below expectations" as a phrase meaning "below the wealthy". The
larger model is substantially better. So Kiswahili uses the larger model, and a
native-speaker review is an acceptance criterion for user testing.

**"What does it cost to run?"**
1.19 cents per bilingual report, measured rather than estimated. About $2.36
projected for the entire project.

**"What's not done?"**
The frontend, offline sync, and the report generation module. The RAG half is
validated but not yet built into the application. I deliberately built in order
of risk — the uncertain parts first, the predictable parts last.

**"Why is the frontend so plain?"**
It's a test harness, not the product. Phase 3 builds the React and Next.js
interface. Building the UI last, against a working backend rather than mocks,
was a deliberate sequencing decision.

**"What would you do differently?"**
Twice I found that an apparent model failure was actually a flawed measurement
— once with the ability correlation, once when my grounding checker scored an
ungrounded report as grounded. Both were caught by control conditions. I'd build
the control arm first next time, rather than adding it after a suspicious result.

---

## 8. Numbers to know cold

| Number | What it is |
|---|---|
| **0.97 / 0.95 / 0.94** | Synthetic recovery of difficulty, discrimination, ability |
| **−0.627** | Item difficulty vs observed pass rate on real data |
| **0.380 → 0.746** | Ability correlation at 1 vs 10 responses per learner — the minimum-responses rule |
| **5 / 10** | Minimum items for an estimate / for a confident one |
| **−1.80 → −1.74** | Chebet's true vs recovered ability |
| **8.3 / 16.8 / 90.1 seconds** | Calibration time at 100 / 200 / 400 items — why batching |
| **1,617 + 923** | Curriculum chunks + assessment rubric rows harvested |
| **64.3% → 100%** | Retrieval accuracy without / with grade + area filtering |
| **26%** | Share of sub-strand titles repeating across grades |
| **1.19 cents** | Per bilingual report |
| **51** | Tests passing |
| **5 in 15 minutes** | Failed logins before the throttle refuses |

---

## 9. Language

**Use:** ability estimate, calibration, strand, sub-strand, item, learner,
discrimination, difficulty, flagged, intervention queue, grounded.

**Avoid:** "the AI figures out", "it learns", "training the model" (for the IRT
part), "accuracy" without saying accuracy of what.

**If you don't know something, say so.** "I haven't measured that yet" is a
complete answer and a much better one than a guess. You have measurements for
an unusual amount of this project; the contrast makes an honest gap look
deliberate rather than careless.

---

## 10. If something breaks

- **Page won't load** — is uvicorn still running? Is Docker running?
  `docker compose up -d`
- **503, database unreachable** — `docker compose up -d`, wait ten seconds
- **No learners** — `python -m app.seed --reset` from `backend`
- **Port 8000 already in use** — an earlier uvicorn is still alive. Close that
  terminal, or run on `--port 8001` and use that in the browser
- **401 in `/docs` mid-demo** — your token expired. Log in again, re-authorize.
  Don't explain it as a bug; it's a 60-minute token doing its job
- **Chebet already flagged on the first assessment** — you rehearsed without
  resetting. `python -m app.seed --reset`, restart uvicorn, reload the page
- **429 on a login you meant to work** — you tripped your own throttle while
  demonstrating Step 3b. Wait, or restart uvicorn: the counter is in memory, so
  a restart clears it. Worth saying out loud if it happens — it proves the
  in-process limitation you already admitted to
- **Anything else** — show `tasks ci` passing and the GitHub Actions tab
  instead. Tests and CI are evidence too

Have a screen recording of a working demo as a backup. Five minutes to make,
and it removes the worst scenario entirely.

---

## 11. Two questions this week's work opened up

**"Have you trained a model?"** No, and the distinction matters. IRT is a
statistical measurement model, not a learned one — there are no weights, and
no saved model file anywhere in the repository. Item parameters are re-estimated
by marginal maximum likelihood every time a strand is calibrated, because
difficulty is a property of an item *relative to the cohort sitting it*.
Freezing one cohort's estimates and applying them to the next would
misestimate ability with false confidence. The Riiid work validated the
estimation *method*; it produced nothing that ships.

**"Why not a neural knowledge-tracing model?"** Interpretability. A teacher can
be shown exactly why a learner was flagged: this item, this difficulty, this
ability estimate, this threshold, twice in a row. A neural model would likely
predict the next answer better and could not justify an intervention decision
about a specific child. The users are teachers acting on these outputs, so
explicability outranks predictive accuracy.
