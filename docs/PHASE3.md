# Phase 3 — Frontend

Next.js in `frontend/`, TypeScript, Tailwind, App Router. Built against the
Phase 2.5 endpoints rather than mocks.

Four stages. **Stage 1 is complete**: the shell, authentication, and a
placeholder dashboard that proves the chain works end to end.

| Stage | What | Done when |
|---|---|---|
| **1** | Scaffold, login, protected routes, token refresh | Sign in, reload, stay signed in ✅ |
| 2 | Classrooms and learners: list, create, enrol, withdraw | A class created through the UI appears in the API |
| 3 | Learner detail, competency heatmap, intervention queue | Otieno renders as "insufficient evidence", not a blank |
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
