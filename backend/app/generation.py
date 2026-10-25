"""
Generating draft questions for a strand: the endpoint, the cap, the worker.

Runs the way reports do, for the same reason: a model call takes long enough
that a phone's connection or a proxy in front of the server would give up
waiting. The POST answers 202 with a pending run; the work happens after the
response; the screen polls GET /api/generation-runs/{id}.

Agreed 20 October:
  * any teacher may generate, for a strand some class at their school uses
  * at most RUNS_PER_DAY runs per school per day (Kenyan time), counting
    runs that did not fail - a provider outage should not use up the day
  * QUESTIONS_PER_RUN questions per run, so review stays manageable on a phone
  * every question is saved as a DRAFT. Nothing generated reaches a learner
    until a teacher approves it (item_status.SERVED)

The model and effort are a starting point, not a measurement: Haiku, as
reports use, at medium effort because writing a correct key and believable
wrong options is harder than summarising. Checkpoint 6 measures them.
"""

from __future__ import annotations

import json
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import repository as repo
from .auth import current_teacher
from .catalogue import Row, catalogue_rows, lookup
from .curriculum import get_embedder
from .db import get_session
from .item_status import AI, DRAFT
from .models import GenerationRun, Item, Strand, Teacher
from .questions import (
    SCHEMA,
    SubStrand,
    build_prompt,
    cosine,
    misconceptions_from,
    normalise,
    option_parts,
    question_problems,
    shuffle_options,
)
from .reporting import provider_detail, provider_errors, worker_session
from .reports import MODEL, get_generator, price, report_text

router = APIRouter(prefix="/api", tags=["question generation"])

EFFORT = "medium"
# Raised from 8,000 on 21 October: a medium-effort Kiswahili run spent 6,638
# tokens thinking and was cut off (run 20261021_095316, 1 of 68). Only what
# is used is billed, so the higher ceiling costs nothing until it is needed.
MAX_TOKENS = 16000
QUESTIONS_PER_RUN = 5
RUNS_PER_DAY = 5
# A new question this close to one already in the bank, by sentence-embedding
# cosine, is a paraphrase rather than a new question. Set from 50 question
# pairs labelled by hand (run 20261025_073023, 14 marked the same): at 0.95,
# 9 of the 11 pairs flagged were the same question (82%) and 9 of the 14 were
# caught; at the first guess of 0.90, only 10 of 19 flagged were the same
# (53%). Between 0.90 and 0.95 sat 8 pairs, 7 of them different questions, so
# 0.90 threw away good questions to catch one duplicate - which a teacher
# reviewing the draft can reject anyway.
DUPLICATE_SIMILARITY = 0.95
# Kenya keeps East Africa Time all year, so a fixed offset is exact - and,
# unlike a zoneinfo lookup, needs no time-zone database on Windows.
EAT = timezone(timedelta(hours=3))
STALE_AFTER = timedelta(minutes=5)

PENDING, READY, FAILED = "pending", "ready", "failed"


class Unusable(Exception):
    """The model answered, but not with something that can be used."""


@dataclass(frozen=True)
class Job:
    """Everything the worker needs, gathered while the request's session is
    open - it is closed before a background task runs."""

    run_id: uuid.UUID
    strand_id: uuid.UUID
    requested_by: uuid.UUID
    prompt: str
    chunks: tuple[tuple[int | None, str], ...]  # (corpus row, text)
    existing: tuple[str, ...]


class GenerateBody(BaseModel):
    count: int = Field(default=QUESTIONS_PER_RUN, ge=1, le=QUESTIONS_PER_RUN)


class RunOut(BaseModel):
    run_id: str
    strand_id: str
    status: str
    requested: int
    produced: int
    dropped: list[dict]
    error: str | None
    item_ids: list[str]
    remaining_today: int
    # What the run cost and how long it took, for measurement.
    cost_usd: float | None = None
    duration_ms: int | None = None


# --- the pure-ish parts ----------------------------------------------------
def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def start_of_today(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(timezone.utc)).astimezone(EAT)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def runs_today(session: Session, school_id: uuid.UUID) -> int:
    """Runs that count against the cap: today in Kenya, and not failed.

    Filtered in Python because SQLite hands the timestamp back without a time
    zone and PostgreSQL with one; the cap is small, so the rows are few.
    """
    since = start_of_today()
    recent = session.scalars(
        select(GenerationRun)
        .where(GenerationRun.school_id == school_id, GenerationRun.status != FAILED)
        .order_by(GenerationRun.created_at.desc())
        .limit(RUNS_PER_DAY * 4)
    )
    return sum(1 for r in recent if _aware(r.created_at) >= since)


def _stale(run: GenerationRun) -> bool:
    return (
        run.status == PENDING
        and datetime.now(timezone.utc) - _aware(run.created_at) > STALE_AFTER
    )


def _resolve_stale(session: Session, run: GenerationRun) -> None:
    if _stale(run):
        run.status = FAILED
        run.error = (
            "The server was interrupted while these questions were being written. "
            "Nothing was saved, and this run does not count against today's limit."
        )
        session.commit()


def failure_text(exc: BaseException) -> str:
    if isinstance(exc, RuntimeError):
        return str(exc)
    if isinstance(exc, provider_errors()):
        return provider_detail(exc).replace("no report was", "no questions were")
    return (
        f"The questions could not be written: an unexpected {type(exc).__name__} "
        "in the server. The server log has the traceback."
    )


def _out(session: Session, run: GenerationRun) -> RunOut:
    item_ids = session.scalars(
        select(Item.item_id).where(Item.generation_run_id == run.run_id)
    )
    return RunOut(
        run_id=str(run.run_id),
        strand_id=str(run.strand_id),
        status=run.status,
        requested=run.requested,
        produced=run.produced,
        dropped=run.dropped or [],
        error=run.error,
        item_ids=[str(i) for i in item_ids],
        remaining_today=max(0, RUNS_PER_DAY - runs_today(session, run.school_id)),
        cost_usd=run.cost_usd,
        duration_ms=run.duration_ms,
    )


# --- the worker ------------------------------------------------------------
def call_model(prompt: str, effort: str = EFFORT) -> tuple[list[dict], object, bool]:
    """The model's questions, its usage, and whether it was cut off.

    `effort` is a parameter only so the measurement spike can compare
    settings through this same call; production always uses EFFORT.
    """
    response = get_generator()(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    truncated = getattr(response, "stop_reason", None) == "max_tokens"
    if truncated:
        return [], response.usage, True
    data = json.loads(report_text(response))
    return list(data.get("questions", [])), response.usage, False


def check_all(
    proposed: list[dict], job: Job, embed=None
) -> tuple[list[dict], list[dict]]:
    """Split the model's questions into those to save and those to drop."""
    texts = [text for _row, text in job.chunks]
    embed = embed or get_embedder()
    keep: list[dict] = []
    dropped: list[dict] = []
    candidates: list[tuple[dict, list[str]]] = [
        (q, question_problems(q, texts)) for q in proposed
    ]

    seen_text = [(q, normalise(q)) for q in job.existing]
    seen_vecs = embed(list(job.existing)) if job.existing else []
    for q, problems in candidates:
        question = (q.get("question") or "").strip()
        if not problems:
            vec = embed([question])[0]
            if any(normalise(question) == n for _t, n in seen_text):
                problems.append("it repeats a question already in the bank")
            else:
                closest = max((cosine(vec, v) for v in seen_vecs), default=0.0)
                if closest >= DUPLICATE_SIMILARITY:
                    # The bank, or an earlier question in this same run.
                    problems.append(
                        f"it is a near-copy of another question (similarity {closest:.2f})"
                    )
        if problems:
            # The whole proposal, not just its wording: what the model got
            # wrong is the measurement, and it cannot be recovered later.
            dropped.append({"question": question, "problems": problems, "proposed": q})
            continue
        keep.append(q)
        # Later questions in the same run are checked against this one too.
        seen_text.append((question, normalise(question)))
        seen_vecs = [*seen_vecs, vec]
    return keep, dropped


def _excerpt_row(excerpt: str, chunks: tuple[tuple[int | None, str], ...]) -> int | None:
    wanted = normalise(excerpt)
    return next((row for row, text in chunks if wanted in normalise(text)), None)


def fill_run(job: Job, session: Session | None = None) -> None:
    """Write the drafts onto a run that already exists. Every failure is an
    outcome written on the run, never an exception lost in a thread."""
    own = session is None
    session = session or worker_session()
    try:
        run = session.get(GenerationRun, job.run_id)
        if run is None or run.status != PENDING:
            return
        started = time.perf_counter()
        try:
            proposed, usage, truncated = call_model(job.prompt)
            run.model, run.effort = MODEL, EFFORT
            run.input_tokens = getattr(usage, "input_tokens", None)
            run.output_tokens = getattr(usage, "output_tokens", None)
            run.cost_usd = price(MODEL, usage)
            if truncated:
                raise Unusable("The model's answer was cut off before it finished. "
                               "Nothing was saved; trying again is reasonable.")
            keep, dropped = check_all(proposed, job)
            for n, q in enumerate(keep):
                texts, misconceptions = option_parts(q)
                # Seeded by the run and position, so a run's order can be
                # reproduced, but different from one question to the next.
                texts, misconceptions, key = shuffle_options(
                    texts, misconceptions, int(q["correct_option"]),
                    random.Random(f"{job.run_id}:{n}"),
                )
                session.add(
                    Item(
                        strand_id=job.strand_id,
                        question_text=q["question"].strip(),
                        options=texts,
                        correct_option=key,
                        rationale=q["rationale"].strip(),
                        misconceptions=misconceptions_from(misconceptions, key),
                        curriculum_excerpt=q["excerpt"].strip(),
                        curriculum_source_row=_excerpt_row(q["excerpt"], job.chunks),
                        status=DRAFT,
                        source=AI,
                        created_by=job.requested_by,
                        generation_run_id=job.run_id,
                    )
                )
            run.produced, run.dropped, run.status = len(keep), dropped, READY
        except Unusable as exc:
            run.status, run.error = FAILED, str(exc)
        except json.JSONDecodeError:
            run.status = FAILED
            run.error = ("The model's answer was not the structured list asked for. "
                         "Nothing was saved; trying again is reasonable.")
        except Exception as exc:  # recorded on the run, then logged
            session.rollback()
            run = session.get(GenerationRun, job.run_id)
            if run is None:
                return
            run.status, run.error = FAILED, failure_text(exc)
            print(f"generation failed: {type(exc).__name__}: {exc}")
        run.duration_ms = int((time.perf_counter() - started) * 1000)
        session.commit()
    finally:
        if own:
            session.close()


# --- endpoints -------------------------------------------------------------
@router.post("/strands/{strand_id}/generate", response_model=RunOut, status_code=202)
def generate_questions(
    strand_id: uuid.UUID,
    background: BackgroundTasks,
    body: GenerateBody | None = None,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
    rows: list[Row] = Depends(catalogue_rows),
) -> RunOut:
    body = body or GenerateBody()
    strand = session.get(Strand, strand_id)
    if strand is None or strand not in repo.school_strands(session, teacher.school_id):
        raise HTTPException(status_code=404, detail="No class at your school uses that strand")
    entry = lookup(rows, strand.curriculum_key) if strand.curriculum_key else None
    if entry is None or not entry.chunks:
        raise HTTPException(
            status_code=409,
            detail="This strand is not linked to a sub-strand in the curriculum catalogue, "
            "so there is no curriculum text to write questions from.",
        )

    pending = session.scalars(
        select(GenerationRun).where(
            GenerationRun.strand_id == strand_id,
            GenerationRun.school_id == teacher.school_id,
            GenerationRun.status == PENDING,
        )
    ).all()
    for run in pending:
        _resolve_stale(session, run)
    if any(r.status == PENDING for r in pending):
        raise HTTPException(
            status_code=409,
            detail="Questions for this strand are already being written. They will "
            "appear for review when they are done.",
        )
    if runs_today(session, teacher.school_id) >= RUNS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail=f"Your school has used today's {RUNS_PER_DAY} question-writing "
            "runs. More can be written tomorrow.",
        )

    existing = tuple(
        session.scalars(
            select(Item.question_text)
            .where(Item.strand_id == strand_id)
            .order_by(Item.created_at)
        )
    )
    chunks = tuple((r.source_row, r.syllabus_text) for r in entry.chunks)
    sub = SubStrand(
        grade=entry.grade, learning_area=entry.learning_area, strand=entry.strand,
        number=entry.number, name=entry.name, language=entry.language,
    )
    run = GenerationRun(
        strand_id=strand_id, school_id=teacher.school_id,
        requested_by=teacher.teacher_id, requested=body.count, status=PENDING,
    )
    session.add(run)
    session.commit()

    job = Job(
        run_id=run.run_id, strand_id=strand_id, requested_by=teacher.teacher_id,
        prompt=build_prompt(sub, [t for _r, t in chunks], body.count, existing),
        chunks=chunks, existing=existing,
    )
    background.add_task(fill_run, job)
    return _out(session, run)


@router.get("/generation-runs/{run_id}", response_model=RunOut)
def get_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> RunOut:
    run = session.get(GenerationRun, run_id)
    if run is None or run.school_id != teacher.school_id:
        raise HTTPException(status_code=404, detail="No such run")
    _resolve_stale(session, run)
    return _out(session, run)


class StrandGenerationOut(BaseModel):
    remaining_today: int
    per_run: int
    # The run still being written, if any, so a reloaded page can keep
    # polling it; otherwise the most recent one, so its outcome is shown.
    running: RunOut | None
    last: RunOut | None


@router.get("/strands/{strand_id}/generation", response_model=StrandGenerationOut)
def strand_generation(
    strand_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> StrandGenerationOut:
    strand = session.get(Strand, strand_id)
    if strand is None or strand not in repo.school_strands(session, teacher.school_id):
        raise HTTPException(status_code=404, detail="No class at your school uses that strand")
    latest = session.scalars(
        select(GenerationRun)
        .where(GenerationRun.strand_id == strand_id,
               GenerationRun.school_id == teacher.school_id)
        .order_by(GenerationRun.created_at.desc())
        .limit(1)
    ).first()
    if latest is not None:
        _resolve_stale(session, latest)
    running = latest if latest is not None and latest.status == PENDING else None
    return StrandGenerationOut(
        remaining_today=max(0, RUNS_PER_DAY - runs_today(session, teacher.school_id)),
        per_run=QUESTIONS_PER_RUN,
        running=_out(session, running) if running else None,
        last=_out(session, latest) if latest is not None and running is None else None,
    )
