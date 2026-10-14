# Runbook

How to start the system, what each step should print, and what the four
failure modes look like when it does not.

Every command below is Windows `cmd` **from the repository root**,
`C:\dev\elimu-analytics`. The `tasks` targets only resolve there, since
`tasks.bat` sits in that directory. The transcript in section 2 is a real run, not an
illustration.

---

## 1. The short version

```cmd
docker compose up -d
tasks seed --reset
tasks run
```

Then <http://127.0.0.1:8000> for the page and
<http://127.0.0.1:8000/docs> for the API.

`tasks seed` and `tasks run` activate the virtual environment themselves. That
is the whole reason they exist: every command in this project needs the venv,
and the error you get without it does not say so.

---

## 2. The long version, with expected output

### Step 1 — the database

```cmd
docker compose up -d
```

```
[+] Running 1/1
 ✔ Container elimu-postgres  Started    1.3s
```

Docker Desktop must already be running. Starting it takes 30–60 seconds from
cold; wait for **Engine running** in the bottom-left of its window, or for
`docker ps` to print a table rather than an error.

### Step 2 — schema and demonstration data

```cmd
tasks seed --reset
```

```
dropped all tables
schema created
seeded: 1 school, 2 teacher accounts, 1 classroom, 1 strand, 12 items,
        40 students, 471 responses

  teacher@example.school / elimu-demo   (role: teacher)
  head@example.school    / elimu-demo   (role: school_admin)
```

`--reset` drops everything first. **Use it after any schema change**, and
before any demonstration — see section 4.

### Step 3 — the server

```cmd
tasks run
```

```
INFO:     Will watch for changes in these directories: ['C:\dev\elimu-analytics\backend']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process using WatchFiles
INFO:     Waiting for application startup.
WARNING: JWT_SECRET is unset, so tokens are signed with the published
         development key. Set JWT_SECRET before any deployment.
INFO:     Application startup complete.
```

**The JWT warning is correct behaviour, not a fault.** The application prints
it deliberately whenever the development signing key is in use, because a
default signing key is not a weak secret — it is a published one. Set
`JWT_SECRET` before any deployment and the warning stops.

Leave this window open. Closing it stops the server.

### Step 4 — confirm it works

Open <http://127.0.0.1:8000>. Three learners should be listed. The server
window should log:

```
"GET /api/health HTTP/1.1" 200 OK
"GET /api/learners HTTP/1.1" 200 OK
```

A `404` for `/favicon.ico` is the browser asking for an icon that does not
exist. Ignore it.

---

## 3. Failure modes

These are the four that actually happen, with the exact text each produces.

### "The system cannot find the file specified" from Docker

```
error during connect: this error may indicate that the docker daemon is not
running: ... open //./pipe/docker_engine: The system cannot find the file specified.
```

**Docker Desktop is not running.** Start it, wait for *Engine running*, confirm
with `docker ps`, then retry. Nothing is wrong with the project.

### "No module named 'girth'" or "No module named uvicorn"

```
ModuleNotFoundError: No module named 'girth'
C:\...\Python312\python.exe: No module named uvicorn
```

**The virtual environment is not activated**, so the command ran against the
system Python, which has none of the project's dependencies. The giveaway is
the interpreter path in the second error: `AppData\Local\Programs\Python`
rather than `.venv`.

Use `tasks seed` and `tasks run`, which activate it for you. If you need a
shell of your own:

```cmd
.venv\Scripts\activate
```

Your prompt then begins with `(.venv)`. That prefix is the thing to check for.

This error is misleading because it names a package rather than the cause, and
it appears identical to a broken install. It is not one.

### A column does not exist

An error naming a column such as `classroom.name`, `student.is_active` or
`student.withdrawn_with_class` means the database predates a schema change.

```cmd
tasks seed --reset
```

**From the browser this does not look like a database problem at all.** The
frontend shows a red `Internal Server Error` banner and nothing else, because
that is all a 500 carries; the column name is printed only in the terminal
running `tasks run`. The rule: when the interface reports a server error, read
the backend terminal before looking at any frontend code.

**Whenever the schema changes, reseed.** `app.seed` calls `create_all`, which
creates missing tables but never alters existing ones, so an added column
appears in the models and not in the database. Any change to `models.py` -
pulled from the repository or made locally - means `tasks seed --reset` before
the application will run.

### "'tasks' is not recognized"

```
'tasks' is not recognized as an internal or external command,
operable program or batch file.
```

**You are not in the repository root.** `tasks.bat` lives at
`C:\dev\elimu-analytics`, and Windows looks for it in the current directory.
Running it from `backend\` or anywhere else fails.

```cmd
cd /d C:\dev\elimu-analytics
```

Every `tasks` command is run from the root. The targets change directory
themselves where they need to.

### Port 8000 already in use

An earlier `uvicorn` is still running in another window. Close that window, or
start on another port and use it in the browser:

```cmd
.venv\Scripts\activate
cd backend
python -m uvicorn app.main:app --reload --port 8001
```

---

## 4. Before a demonstration

Assessment results are recorded, so **rehearsing changes what the next run
shows**. The intervention queue is only empty if no assessment has been run
since the last reset, and the two-consecutive-assessment behaviour is only
visible from a clean state.

Reset immediately before presenting:

```cmd
tasks seed --reset
```

Then, in order: start Docker, seed, start the server, confirm three learners
appear, open `/docs` in a second tab — and **do not log in during setup**.
Tokens last 60 minutes, so a login during pre-flight can expire before the
authenticated part of a demonstration is reached.

Run `tasks ci` during setup too, and leave its output in a spare window. It
takes about 100 seconds, which is far too long to run in front of an audience.

---

## 5. Checks

```cmd
tasks ci       ruff + the full test suite, exactly what GitHub Actions runs
tasks test     the suite alone
tasks lint     ruff alone
tasks fix      ruff with autofix
```

**69 tests**, on SQLite, so no Docker is needed for them.

The suite takes roughly 100 seconds, most of it bcrypt. The authentication,
throttling and classroom tests hash real passwords, and bcrypt is deliberately
slow — that cost is the mechanism working rather than a problem to fix.

Two deprecation warnings are expected, both from `starlette` and `anyio`
rather than from this codebase. The `httpx2` suggestion in the first is best
ignored: that package was the source of three dependency collisions during
Phase 0.

### A test passes here and fails there

If `tasks ci` fails on a test that passed elsewhere, suspect the test before
the code. The cause is usually a library behaving differently between
versions - `httpx`'s cookie jar did exactly this to two refresh-token tests.
Reproduce it in isolation (`pytest backend/tests/test_x.py -q`), and prefer a
test that depends on nothing version-specific over one that happens to pass.

---

## 6. Line endings

`git add` prints a warning for most files:

```
warning: in the working copy of 'README.md', LF will be replaced by CRLF
the next time Git touches it
```

This is normal and needs no action. Git stores LF in the repository and hands
Windows a CRLF working copy, which is the standard `core.autocrlf` behaviour.

It is **not** the same as the phantom diff that appeared once during Phase 2,
where eleven files showed 29,097 insertions and 29,097 deletions — identical
counts, meaning no line had actually changed. That was CRLF having reached the
index itself, and it was cleared with:

```cmd
git checkout -- <paths>
```

If that reappears and does not clear, the permanent fix is a `.gitattributes`
file pinning the repository to LF. It is not committed yet, deliberately:
adding one triggers a one-time renormalisation that rewrites every file, which
is not something to do casually mid-project.
