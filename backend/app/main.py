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

import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import repository as repo
from .auth import current_teacher
from .auth import router as auth_router
from .calibration import assess_strand, calibrate_strand, open_flags
from .db import get_session, healthcheck
from .irt import ResponseMatrixError
from .items import router as items_router
from .models import Teacher
from .security import secret_is_default

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="Elimu Analytics", version="0.3.0")
app.include_router(auth_router)
app.include_router(items_router)


@app.on_event("startup")
def warn_about_dev_secret() -> None:
    if secret_is_default():
        print(
            "WARNING: JWT_SECRET is unset, so tokens are signed with the published "
            "development key. Set JWT_SECRET before any deployment."
        )


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


@app.get("/api/learners")
def learners(session: Session = Depends(get_session)) -> list[dict]:
    """The three named learners from the demonstration classroom."""
    named = [s for s in repo.list_students(session) if not s.name.startswith("Learner ")]
    return [{"id": str(s.student_id), "name": s.name} for s in named]


@app.get("/api/diagnose/{student_id}")
def diagnose(student_id: str, session: Session = Depends(get_session)) -> dict:
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


@app.get("/api/flags")
def flags(
    session: Session = Depends(get_session),
    _: Teacher = Depends(current_teacher),
) -> list[dict]:
    """The intervention queue: learners flagged and not yet resolved."""
    out = []
    for f in open_flags(session):
        student = repo.list_students(session)
        name = next((s.name for s in student if s.student_id == f.student_id), "?")
        out.append({
            "flag_id": str(f.flag_id),
            "learner": name,
            "severity": f.severity,
            "flagged_at": f.flagged_at.isoformat() if f.flagged_at else None,
        })
    return out


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")
