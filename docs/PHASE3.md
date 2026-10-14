# Phase 3 — Frontend

Next.js in `frontend/`, TypeScript, Tailwind, App Router. Built against the
Phase 2.5 endpoints rather than mocks.

Four stages. **Stage 1 is complete**: the shell, authentication, and a
placeholder dashboard that proves the chain works end to end.

| Stage | What | Done when |
|---|---|---|
| **1** | Scaffold, login, protected routes, token refresh | Sign in, reload, stay signed in ✅ |
| **2** | Classrooms and learners: list, create, enrol, withdraw | A class created through the UI appears in the API ✅ |
| **3** | Learner detail, competency heatmap, intervention queue | Otieno renders as "insufficient evidence", not a blank ✅ |
| **4** | Quiz administration: present items, capture, submit | A response recorded in the UI changes θ ✅ |

---

## Run it

Two processes. Backend first:

```cmd
docker compose up -d
tasks seed --reset
tasks run              http://127.0.0.1:8000
```

Then, in a second terminal:

```cmd
cd frontend
npm install            once
cd ..
tasks web              http://localhost:3000
```

Sign in with `head@example.school` / `elimu-demo`.

`tasks webci` runs lint, typecheck and build — what the frontend CI job runs.

---

## Why the dev server proxies `/api`

`next.config.ts` rewrites `/api/:path*` to the FastAPI service. The browser
therefore sees a single origin, which matters for one specific reason: the
refresh cookie is first-party, so `SameSite=Lax` holds and never has to be
weakened to `none` to make local development work. Weakening it in
development is how it ends up weakened in production.

`NEXT_PUBLIC_API_URL` overrides the target if the backend is not on port 8000.

---

## Where the access token lives

In a module variable in `lib/api.ts`. Not `localStorage`, not
`sessionStorage`, not a readable cookie — anything a script can read is
something an injected script can steal, and these accounts reach children's
assessment records.

The cost is that it dies on reload. The refresh cookie repairs that, and
`lib/auth.tsx` asks it before the app decides anything.

### Three behaviours in the client worth knowing

**Every request retries once after a 401.** The access token lives fifteen
minutes, so expiry mid-session is ordinary. The client refreshes and repeats
the request; the calling component never learns it happened.

**Concurrent refreshes are collapsed into one.** A dashboard fires several
requests at once, and if the token has just expired they all receive a 401 at
the same moment. Refreshing per request would spend several single-use tokens
simultaneously — and the backend's rotation logic would read the second one as
a replay and revoke the whole family, signing the teacher out for the offence
of loading a page with three panels on it. So the first refresh is stored as a
promise and the others await it.

**`credentials: "include"` on every request.** The refresh cookie is httpOnly,
so script cannot attach it. The browser will, but only if asked.

---

## The three-state session

`lib/auth.tsx` distinguishes states that are easy to conflate:

```
"unknown"   the page just loaded; the refresh cookie has not answered yet
"guest"     asked, and there is no session
"signed in"
```

The guard in `components/Guard.tsx` waits for `resolved` before redirecting.
Treating "unknown" as "guest" is the classic bug here: every valid session
flashes the login page for a moment on each reload, because for a few hundred
milliseconds the app genuinely does not know who you are.

---

## Typing the refusal

`DiagnosticCell.theta` is `number | null` and `status` is a union of
`"estimated" | "provisional" | "insufficient_evidence"`.

That null is not a missing value or an error. It is the system declining to
estimate a learner's ability from too few answers, which is the most important
behaviour the interface has to convey. Typing it as nullable means the
compiler will not let a component render it without deciding what to show
instead — so the Stage 3 heatmap cannot accidentally display a blank cell
where a deliberate refusal belongs.

---

## Layout

```
frontend/
├── app/
│   ├── layout.tsx            AuthProvider wraps everything
│   ├── page.tsx              decides: dashboard or login
│   ├── login/page.tsx
│   └── (app)/                route group: everything behind the guard
│       ├── layout.tsx        Guard + TopBar
│       └── dashboard/page.tsx
├── components/
│   ├── Guard.tsx             waits for `resolved`, then redirects
│   └── TopBar.tsx
├── lib/
│   ├── api.ts                token, refresh, retry
│   ├── auth.tsx              session context
│   └── types.ts              the backend's response shapes
└── legacy/index.html         the Phase 1 page, still served at :8000
```

The Phase 1 page moved from `frontend/index.html` to `frontend/legacy/` so
that Next.js could take `frontend/` as its project root; `main.py` points at
the new path. It is kept deliberately: it exercises the API with no build
step, which is useful precisely when the frontend is broken.

---

## Stage 2 — classrooms and learners

Two pages: `/classrooms` lists the school's classes, `/classrooms/[id]` is one
class's roll. Between them they drive every endpoint from the scoping work.

**There is no school filter, because there is nothing to filter.** The API
returns the caller's own school and nothing else, so the interface has no
control for it and no way to ask for another. Scoping that is invisible in the
UI is scoping that cannot be got around by the UI.

**Create and withdraw are hidden from a plain teacher.** Hiding is cosmetic -
the server enforces the role regardless - and the code says so, because an
interface that only hides is not access control.

**Removal reports the server's own words.** The API decides whether a record
is deleted or withdrawn and explains why; the page prints that `detail`
verbatim rather than paraphrasing it. A paraphrase drifts, and "deleted" when
the record was actually kept is exactly the kind of quiet untruth this project
is built to avoid.

**The roll shows response counts, with "kept on removal" beside any learner
who has answered something.** That count is what decides deletion versus
withdrawal, so a teacher can see the consequence before clicking rather than
discover it in a notice afterwards.

### A React 19 rule worth knowing

`react-hooks/set-state-in-effect` rejects an effect that calls a function
which sets state - including an async one, and including a `useCallback`
several lines away. The accepted shape is an async IIFE inside the effect,
with a `cancelled` flag, owning its own `setState` calls:

```tsx
const fetchRows = useCallback(() => api.get<Classroom[]>(url), [url]);

useEffect(() => {
  let cancelled = false;
  (async () => {
    try {
      const data = await fetchRows();
      if (!cancelled) setRows(data);
    } catch (e) {
      if (!cancelled) setError(errorMessage(e, "..."));
    }
  })();
  return () => { cancelled = true; };
}, [fetchRows]);
```

Fetching and storing are therefore kept apart in both pages, with a separate
`reload()` for event handlers, which the rule does not police. The `cancelled`
flag is not ceremony: without it a response arriving after the component
unmounts sets state on something that no longer exists.

---

## Stage 3 — diagnostics

Three pages. `/classrooms/[id]` is now the competency heatmap and the default
view of a class, with the roll moved to `/classrooms/[id]/roll`;
`/students/[id]` is one learner across every strand; `/flags` is the
intervention queue.

The heatmap leads rather than sitting behind the queue because **the queue is
a conclusion and the heatmap is the evidence for it.** A teacher who only ever
sees the queue has to take the flagging on trust.

### How a cell is drawn, and why

Each cell is a faint tint of the tier colour, a solid 4px band at its left
edge, and the tier written in words with θ beneath.

**The text never sits on the ramp colour.** Contrast is the surface's, so it
cannot fail at any step of the ramp - a problem that filled heatmap cells
usually have at one end or the other.

**Darker means more need, not more ability.** Encoding ability would put the
heaviest ink on the learners who need nothing. The cells a teacher must act on
are the ones that carry weight on the page.

**One hue, four ordinal steps, validated.** The ramp was checked against the
light surface and separately against the dark one: monotone lightness, every
adjacent step clearing the gap floor, and the lightest step still separating
from the surface. The dark mode is its own set of steps from the same hue,
re-ordered so that "most need stands out most" still holds when prominence
runs the other way.

**Deliberately not red-amber-green.** These are children's competency levels,
not alarms. Colouring a learner red is a framing this project should not
adopt, and a status palette would also collide with the convention that red
means "error" elsewhere in the interface.

**It survives greyscale.** In print and under `forced-colors`, the tints drop
out and the band widens; the ordinal signal is carried by band darkness and
the tier name, never by hue alone. A thesis page printed in black and white
still ranks correctly.

### The refusal is a first-class state

A learner below the evidence threshold gets a hatched neutral cell reading
"no estimate" and "3 of 5 items" - never a blank, which would read as a
rendering fault. The learner page prints the server's own sentence explaining
why, rather than paraphrasing it.

This is the behaviour the type system was arranged to force: `theta` is
`number | null`, so a component cannot render it without deciding what to show
when there is nothing to show.

### Withdrawal is reversible, and the reversal is exact

Removing a classroom withdraws its learners too, so restoring it has to bring
them back - but only the ones that action took. A learner a teacher withdrew
deliberately beforehand must stay withdrawn, or restoring a classroom silently
reverses a decision somebody made about a child.

`Student.withdrawn_with_class` records which of the two happened, so the undo
reverses what the action did rather than approximating it. Restoring a learner
individually clears the flag, so a later class restore does not reach for them
again. Six tests cover it, including the asymmetry.

An action that is easy to do and hard to undo is the wrong shape, particularly
behind a button labelled "Remove".

### Assessment runs from the page that shows its results

The heatmap has **Recalibrate** and **Run assessment**, which do different
things and are deliberately separate from each other and from viewing.
Calibration re-estimates item parameters; assessment records an ability
estimate per learner and is an event in that learner's record, not a side
effect of opening a page.

The notice afterwards reports estimates recorded, learners skipped for too
little evidence, and flags raised - and when none were raised, says why: a
flag needs two consecutive below-threshold assessments, so the first run never
produces one. Without that, an empty queue after an assessment looks broken.

### The queue says what an empty queue means

"Nobody is flagged" is ambiguous and could be read as reassurance, so the
empty state says that a flag needs two consecutive below-threshold assessments
and that an empty queue early in a term is expected rather than comforting.

---

## Stage 4 — marking a quiz

`/classrooms/[id]/quiz` is a grid of learners by items. It is the page that
finally lets a teacher create the data the rest of the system measures: until
now every response in the database came from `seed.py`.

Four decisions, each forced by the backend rather than chosen for looks.

**Cells are tri-state, not checkboxes.** Blank, correct, wrong. A checkbox
conflates "wrong" with "not attempted", and the response matrix treats those
as entirely different: an unanswered item is excluded from the estimate, a
wrong one pulls it down. Submitting blanks as zeroes would bias every ability
estimate in the class downward - the Day 1 sentinel rule, surfacing as an
interface requirement.

**Pairs already recorded are locked**, which needed a new endpoint. The matrix
holds one response per learner and item, so re-answering is refused with 409.
Without knowing which pairs exist, the grid would let a teacher mark one and
then reject the entire batch for a reason they had no way of seeing.
`GET /api/assessments/answered/{class_id}/{strand_id}` returns the taken pairs
so those cells are disabled and the rejection never arises.

**One identifier per batch, generated on the device and reused on retry.**
`client_batch_id` is made when a fresh grid loads and regenerated only after a
submission is known to have landed. A submission that times out and is sent
again therefore carries the same id and is recognised as the same work. This
is the client the idempotency work in Phase 2.5 was built for, and the comment
in the failure branch says explicitly why the id is *not* regenerated there.

**Nothing is saved until Submit.** The grid is local state; a half-marked
class is not a half-recorded assessment.

### The loop closes here

Mark a quiz → Run assessment on the heatmap → the cells move. Twice → the
intervention queue fills. Every number in the system can now originate from a
teacher rather than from the seed.

---

## Stage 4b — learner-facing quiz mode

`/classrooms/[id]/administer` is the screen a child holds. It is the only
place in the application where someone other than the signed-in teacher
touches the device, and that single fact drives the design.

### The containment problem

**The tablet is signed in as the teacher.** A child holding it is holding a
session that can reach the competency heatmap - every classmate's ability
estimate, by name. That is a children's-data disclosure one back-button away,
and it is squarely inside the Data Protection Act territory Chapter 3 covers.

So quiz mode is a boundary rather than a page: it renders over the whole
viewport with no navigation chrome, the browser's Back button is trapped by
re-pushing history state, and leaving re-prompts for the teacher's password.
None of this is a hard lock - nothing in a browser is - but it closes the
realistic case, which is a bored eight-year-old tapping.

### Identity, and the assumption behind it

A learner is identified by **the teacher selecting their name before handing
the device over**. There are no learner accounts and no child PINs: issuing
credentials to primary-school children is a far larger data-protection
surface than this buys, and children lose and share codes.

Identity therefore rests on supervision. That is a real limitation and it
belongs in Chapter 6 stated plainly, not glossed: the system records the
learner the teacher said was answering.

### The device never learns the answers

The quiz endpoint returns question text and options. Its response model has
**no field for the key**, so there is nothing to forget to strip, and the
client submits `selected_option` rather than `correct`. The server marks it.

A learner cannot read the answer off the network tab, because it was never
sent; a modified client cannot report itself correct, because correctness is
not an input.

### The flow

```
setup      pick a strand, Start
roster     tap a name, hand the device over
answering  one question at a time, four options, no going back
handback   "Please give the device back to your teacher"
roster     next learner, or End session
```

There is no Back and no Skip inside a quiz. A child revisiting an earlier
answer after seeing a later question is a different measurement, and there is
no teacher watching the screen to adjudicate.

Answers are held in the page until the teacher ends the session, then sent as
**one batch with one idempotency key** - not regenerated on failure, so a
submission that times out and is retried is recognised as the same work.

### One response per learner and item, enforced before the child answers

The first version of the roster offered every learner. A learner who had
already answered that strand - which, in the demonstration classroom, is all
forty of them - would sit through twelve questions and have the entire batch
refused afterwards with a 409. The rule was right and the moment of enforcing
it was wrong: the cost fell on a child who had done nothing but answer the
questions put in front of them.

The roster now loads the answered pairs when a session starts and shows each
learner what they still owe - "12 question(s) left", "already answered this
strand" - and hands over only the items that learner has not answered. A
learner who answered six of twelve gets the remaining six. The refusal moves
from after the work to before it.

Answers are also marked as taken locally as they are given, so a second
hand-over within the same session cannot ask the same question twice.

### Items without options

An item with only question text is still a valid item: a teacher can ask it
aloud and mark it on the quiz grid. It simply is not delivered to a learner,
because nothing knows what the right answer is. The two modes coexist, and
the setup screen says so when a strand has nothing deliverable.

---

## CI

The workflow now has two jobs. `backend` runs ruff and pytest on Python 3.10
and 3.12; `frontend` runs lint, typecheck and build on Node 20 and 22,
installing with `npm ci` so the lockfile and `package.json` must agree.

The lockfile is committed. Without it `npm ci` cannot run and no build is
reproducible.

### A note on ESLint

`eslint-config-next` 16 exports flat config arrays, so `eslint.config.mjs`
spreads them directly. The `FlatCompat` shim most guides still show crashes
against it with `TypeError: Converting circular structure to JSON`, which
names nothing useful. If you see that error, the cause is the shim, not your
config.

---

## Verified

Installed, linted, typechecked and built on Node 22 before being written to
disk. Four routes prerender: `/`, `/login`, `/dashboard`, `/_not-found`.

What is **not** verified here is the browser behaviour — the sign-in round
trip, the reload, the cookie. Those need the two servers running together, and
the last two bugs in this project were both things no test client reproduced.
