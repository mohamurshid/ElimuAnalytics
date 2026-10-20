"""
Elimu Analytics - Phase 2 backend.

Phase 1 proved the chain connects with an in-memory array. Phase 2 puts
PostgreSQL behind it: the same endpoints, the same numbers, real persistence.

Run:
    docker compose up -d
    python -m app.seed
    uvicorn app.main:app --reload --port 8000
Then open http://127.0.0.1:8000
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import curriculum
from . import repository as repo
from .assessments import router as assessments_router
from .auth import current_teacher
from .auth import router as auth_router
from .calibration import assess_strand, calibrate_strand
from .catalogue import router as catalogue_router
from .class_strands import router as class_strands_router
from .classrooms import router as classrooms_router
from .db import get_session, healthcheck
from .diagnostics import router as diagnostics_router
from .irt import ResponseMatrixError
from .items import router as items_router
from .models import Teacher
from .reporting import router as reports_router
from .security import ALLOWED_ORIGINS, secret_is_default

# The Phase 1 page moved under frontend/legacy/ when the Next.js app took
# frontend/ as its project root. It is kept because it exercises the API with
# no build step, which is a useful thing to have when the frontend is broken.
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "legacy"

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown.

    Replaces the deprecated `@app.on_event("startup")`. Everything before the
    `yield` runs once at startup, everything after it at shutdown.
    """
    if secret_is_default():
        print(
            "WARNING: JWT_SECRET is unset, so tokens are signed with the published "
            "development key. Set JWT_SECRET before any deployment."
        )

    # The sentence-transformer takes 30 seconds to build and was being built
    # inside the first report request, which is how a working endpoint came
    # to look broken for exactly one teacher per restart. On a daemon thread,
    # so startup returns at once and Ctrl-C is never held up by a half-loaded
    # model; nothing waits on it, because get_embedder() takes the same lock
    # and a request arriving mid-load simply blocks until it is ready.
    #
    # ELIMU_WARM_EMBEDDER=0 turns it off, which is worth having under
    # `--reload`: every saved file restarts the worker and would start
    # another 30-second load that the next save throws away.
    if os.environ.get("ELIMU_WARM_EMBEDDER", "1") != "0":
        threading.Thread(
            target=curriculum.warm_embedder, name="warm-embedder", daemon=True
        ).start()

    yield


app = FastAPI(title="Elimu Analytics", version="0.7.0", lifespan=lifespan)
# Credentialed CORS: the refresh cookie only travels if the browser is told
# to send it, and a wildcard origin is forbidden once credentials are allowed -
# which is the specification protecting us from ourselves.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(items_router)
app.include_router(classrooms_router)
app.include_router(assessments_router)
app.include_router(diagnostics_router)
app.include_router(catalogue_router)
app.include_router(class_strands_router)
app.include_router(reports_router)


@app.get("/api/health")
def health(session: Session = Depends(get_session)) -> dict:
    if not healthcheck():
        raise HTTPException(
            status_code=503,
            detail="Database unreachable. Is `docker compose up -d` running?",
        )
    strands = repo.list_strands(session)
    students = repo.list_students(session)
    return {
        "status": "ok",
        "database": "connected",
        "strands": [{"id": str(s.strand_id), "name": s.name} for s in strands],
        "strand": strands[0].name if strands else None,
        "students": len(students),
    }


@app.get("/api/learners", deprecated=True)
def learners(session: Session = Depends(get_session)) -> list[dict]:
    """The three named learners from the demonstration classroom.

    Superseded by `GET /api/classrooms/{id}/students`, which is authenticated,
    school-scoped and returns the whole roll. Kept so the plain HTML page
    continues to work; Phase 3 should not call it.
    """
    named = [s for s in repo.list_students(session) if not s.name.startswith("Learner ")]
    return [{"id": str(s.student_id), "name": s.name} for s in named]


@app.get("/api/diagnose/{student_id}", deprecated=True)
def diagnose(student_id: str, session: Session = Depends(get_session)) -> dict:
    """Superseded by `GET /api/students/{id}/diagnostics`, which is
    authenticated, school-scoped and takes an explicit strand. This one uses
    whichever strand sorts first, which is invisible with one strand and wrong
    with six."""
    strands = repo.list_strands(session)
    if not strands:
        raise HTTPException(status_code=503, detail="No strands. Run `python -m app.seed`.")
    try:
        sid = uuid.UUID(student_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Malformed learner id") from exc

    try:
        result = repo.diagnose_student(session, strands[0].strand_id, sid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ResponseMatrixError as exc:
        # A violated Phase 0 rule is a server-side bug, not a bad request.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result["sub_strand"] = result.pop("strand")
    return result


@app.post("/api/strands/{strand_id}/calibrate")
def calibrate(
    strand_id: str,
    session: Session = Depends(get_session),
    _: Teacher = Depends(current_teacher),
) -> dict:
    """Estimate item parameters for the strand and persist them."""
    try:
        return calibrate_strand(session, uuid.UUID(strand_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ResponseMatrixError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/strands/{strand_id}/assess")
def assess(
    strand_id: str,
    session: Session = Depends(get_session),
    _: Teacher = Depends(current_teacher),
) -> dict:
    """Record an ability estimate for every learner, and raise flags where the
    two-consecutive-assessment rule is met."""
    try:
        return assess_strand(session, uuid.UUID(strand_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ResponseMatrixError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")
