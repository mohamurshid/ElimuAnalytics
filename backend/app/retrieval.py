"""
Filtered retrieval over the curriculum corpus.

    python -m app.retrieval --check        verify pgvector against numpy
    python -m app.retrieval --query "..." --grade "Grade 5" --area "Science and Technology"

THE FILTER IS NOT AN OPTIMISATION
---------------------------------
Measured 17 October against the corpus as it is actually embedded - the
curriculum head, not the whole chunk - by spike/retrieval_at_scale.py, which
now imports embedding_text from this package rather than keeping its own copy.

Two tests, and they are not interchangeable:

  * 300 heading queries over all 1,617 chunks: top-1 46.3%, top-5 72.0%,
    MRR 0.577, mean top1-top2 margin 0.042. The margin is the finding - the
    leading candidates are effectively tied, so retrieval on wording alone is
    guessing. There is no filtered counterpart to this test.
  * 14 realistic queries, teacher phrasing and failed items with curriculum
    vocabulary deliberately avoided: top-1 64.3% unfiltered against 100% with
    grade and learning area applied first, which cuts the candidate set to 8.
    Fourteen queries is a small sample and the figure belongs with its n.

Embedding the head rather than the whole chunk, which was done to stop
MiniLM's 256 word-piece truncation producing identical vectors for different
sub-strands, cost nothing at scale: the September full-text run measured 45.3%
and 64.3% on the same two tests.

The collapse is worst where sub-strand wording repeats across the six grades.
On the 300-query test: 16% for Indigenous Language, 23% for Kiswahili, 25% for
Mathematics, 33% for English - against 93% for Religious Education (HRE), 80%
for IRE and 100% for Agriculture and Nutrition, whose sub-strand names are
distinctive. Religious Education (CRE) sits between at 64%. Semantic
similarity cannot separate six grades of "Listening and Speaking"; only the
metadata can.

So `grade` and `learning_area` are required arguments with no defaults. Passing
None for either is allowed, because the unfiltered case has to remain
measurable, but it has to be asked for explicitly - it is not what you get by
forgetting.

THE SIMILARITY FLOOR
--------------------
Carried over from the Day 5 spike unchanged. Taking the top k by rank alone
admitted a plants chunk scoring 0.133 alongside a heat-transfer chunk scoring
0.355, and the report then cited plant activities for a heat-transfer learner.
A chunk after the first has to clear both an absolute floor and a share of the
top score. The first result is always kept: if the best match is weak, that is
for the caller to judge, and silently returning nothing would look like an
empty corpus.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .curriculum import get_embedder
from .db import get_session_factory
from .models import CurriculumChunk

FLOOR_ABS = 0.25
FLOOR_REL = 0.50
DEFAULT_TOP_K = 2


@dataclass(frozen=True)
class Retrieved:
    """One chunk and how close it was. `similarity` is cosine, 0.0 to 1.0."""

    chunk_id: object
    grade: str | None
    learning_area: str | None
    strand: str | None
    sub_strand: str | None
    syllabus_text: str
    source_id: str | None
    source_row: int | None
    similarity: float


def apply_floor(
    results: list[Retrieved],
    floor_abs: float = FLOOR_ABS,
    floor_rel: float = FLOOR_REL,
) -> list[Retrieved]:
    """Keep the best match, then only those clearing both floors."""
    if not results:
        return []
    cutoff = max(floor_abs, floor_rel * results[0].similarity)
    return [results[0]] + [r for r in results[1:] if r.similarity >= cutoff]


def retrieve(
    session: Session,
    query: str,
    *,
    grade: str | None,
    learning_area: str | None,
    top_k: int = DEFAULT_TOP_K,
    floor: bool = True,
) -> list[Retrieved]:
    """Pre-filter on metadata, rank what survives by cosine distance, then floor."""
    vector = get_embedder()([query])[0]

    # pgvector's <=> is cosine DISTANCE. Embeddings are stored as unit vectors
    # (curriculum.py), so similarity is 1 - distance and the arithmetic is exact
    # rather than approximate.
    distance = CurriculumChunk.embedding.cosine_distance(vector)
    conditions = [CurriculumChunk.embedding.isnot(None)]
    if grade is not None:
        conditions.append(CurriculumChunk.grade == grade)
    if learning_area is not None:
        conditions.append(CurriculumChunk.learning_area == learning_area)

    rows = session.execute(
        select(CurriculumChunk, distance.label("distance"))
        .where(*conditions)
        .order_by(distance)
        .limit(top_k)
    ).all()

    results = [
        Retrieved(
            chunk_id=chunk.chunk_id,
            grade=chunk.grade,
            learning_area=chunk.learning_area,
            strand=chunk.strand,
            sub_strand=chunk.sub_strand,
            syllabus_text=chunk.syllabus_text,
            source_id=chunk.source_id,
            source_row=chunk.source_row,
            similarity=1.0 - float(dist),
        )
        for chunk, dist in rows
    ]
    return apply_floor(results) if floor else results


# ---------------------------------------------------------------------------
# Self-check. Needs the database; not part of the pytest suite, because the
# curriculum_chunk table cannot be created on SQLite (pgvector has no SQLite
# equivalent - see test_repository.py).
# ---------------------------------------------------------------------------
def check(session: Session, grade: str = "Grade 5", area: str = "Science and Technology") -> bool:
    """Does the database rank the way the spike's numpy did?

    This is the invariant that matters before anything is built on top: the
    Day 5 spike ranked chunks with numpy cosine in process, and production
    ranks them with pgvector's <=> operator inside Postgres. If those two
    disagree, every retrieval number measured in the spike describes a system
    that is not the one being shipped.

    It compares them on the SAME stored vectors, so it isolates the operator
    from the corpus. It does not compare similarity values against the spike's
    published figures, and should not: the spike ran on eight hand-written
    chunks whose text differs from the extracted corpus, so the numbers are not
    expected to match and agreement there would prove nothing.
    """
    import numpy as np

    stored = session.execute(
        select(CurriculumChunk)
        .where(
            CurriculumChunk.grade == grade,
            CurriculumChunk.learning_area == area,
            CurriculumChunk.embedding.isnot(None),
        )
        .order_by(CurriculumChunk.source_row)
    ).scalars().all()

    if not stored:
        print(f"no embedded chunks for {grade} / {area} - run `tasks ingest` first")
        return False

    print(f"{len(stored)} embedded chunks for {grade} / {area}")

    matrix = np.array([c.embedding for c in stored], dtype=float)
    norms = np.linalg.norm(matrix, axis=1)
    print(f"stored vector norms: min {norms.min():.6f} max {norms.max():.6f}  (expect 1.0)")
    unit = bool(np.allclose(norms, 1.0, atol=1e-5))
    print(f"  stored as unit vectors: {'yes' if unit else 'NO - cosine arithmetic is off'}")

    query = (
        "A cooking pot is made of metal but its handle is covered with plastic. "
        "Explain why the handle is made of a different material, and name a material "
        "that would keep food warm for longer."
    )
    qv = np.array(get_embedder()([query])[0], dtype=float)
    numpy_order = np.argsort(-(matrix @ qv))

    db = retrieve(session, query, grade=grade, learning_area=area, top_k=len(stored), floor=False)

    print("\nrank  pgvector                                      sim    numpy agrees")
    agree = True
    for position, result in enumerate(db):
        expected = stored[numpy_order[position]]
        same = expected.chunk_id == result.chunk_id
        agree = agree and same
        numpy_sim = float(matrix[numpy_order[position]] @ qv)
        close = abs(numpy_sim - result.similarity) < 1e-5
        agree = agree and close
        label = (result.sub_strand or "")[:42]
        print(f"{position + 1:>4}  {label:<44} {result.similarity:.4f}  "
              f"{'yes' if same and close else 'NO'}")

    print(f"\npgvector and numpy agree on order and score: {'yes' if agree else 'NO'}")

    floored = apply_floor(db)
    print(f"\nsimilarity floor (abs {FLOOR_ABS}, rel {FLOOR_REL} x {db[0].similarity:.3f} "
          f"= {max(FLOOR_ABS, FLOOR_REL * db[0].similarity):.3f}):")
    print(f"  {len(db)} candidates -> {len(floored)} admitted to the prompt")
    for result in floored:
        print(f"    [{result.similarity:.3f}] {result.sub_strand[:60]}")

    return agree and unit


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify pgvector against numpy")
    ap.add_argument("--query")
    ap.add_argument("--grade", default="Grade 5")
    ap.add_argument("--area", default="Science and Technology")
    ap.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    ap.add_argument(
        "--no-floor",
        action="store_true",
        help="show the raw ranking without the similarity floor",
    )
    args = ap.parse_args()

    with get_session_factory()() as session:
        if args.check:
            raise SystemExit(0 if check(session, args.grade, args.area) else 1)
        if not args.query:
            ap.error("pass --query or --check")
        # Without --no-floor this prints what would reach the prompt, which is
        # usually one chunk: at a top score near 0.40 the cutoff is
        # max(0.25, 0.5 x 0.40) = 0.25 and nothing else clears it. That makes
        # --top-k look broken when inspecting a ranking, which is what
        # --no-floor is for.
        results = retrieve(
            session,
            args.query,
            grade=args.grade,
            learning_area=args.area,
            top_k=args.top_k,
            floor=not args.no_floor,
        )
        if not args.no_floor and len(results) < args.top_k:
            print(
                f"(similarity floor applied: {len(results)} of up to {args.top_k} "
                f"admitted. Use --no-floor to see the raw ranking.)\n"
            )
        for position, result in enumerate(results, 1):
            where = f"{result.grade} / {result.learning_area}"
            print(f"{position:>2}. [{result.similarity:.4f}] {where}")
            print(f"    {result.sub_strand}")
            print(f"    source_row {result.source_row} ({result.source_id})\n")


if __name__ == "__main__":
    main()
