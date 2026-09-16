"""
Elimu Analytics - Phase 1 walking skeleton.

One hardcoded strand, a real girth 2-PL calibration, a number on a bare page.
No auth, no database, no styling. The only thing this proves is that the chain
connects: browser -> FastAPI -> girth -> browser.

Run:
    uvicorn app.main:app --reload --port 8000
Then open http://127.0.0.1:8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from . import data
from .irt import ResponseMatrixError, diagnose

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="Elimu Analytics (walking skeleton)", version="0.1.0")


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "strand": data.STRAND,
        "sub_strand": data.SUB_STRAND,
        "items": data.N_ITEMS,
        "students": data.N_STUDENTS,
    }


@app.get("/api/learners")
def learners() -> list[dict]:
    return [{"id": i, "name": n} for i, n in sorted(data.FOCUS_LEARNERS.items())]


@app.get("/api/diagnose/{learner_id}")
def diagnose_learner(learner_id: int) -> dict:
    if learner_id < 0 or learner_id >= data.N_STUDENTS:
        raise HTTPException(status_code=404, detail="No such learner")
    try:
        result = diagnose(
            data.response_matrix(), data.N_ITEMS, data.N_STUDENTS, learner_id
        )
    except ResponseMatrixError as exc:
        # A violated spike rule is a server-side bug, not a bad request.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "learner": data.learner_name(learner_id),
        "strand": data.STRAND,
        "sub_strand": data.SUB_STRAND,
        **result,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")
