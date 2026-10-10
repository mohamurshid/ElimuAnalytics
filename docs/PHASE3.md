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
| 4 | Quiz administration: present items, capture, submit | A response recorded in the UI changes θ |

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
