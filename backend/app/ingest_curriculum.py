"""
Load the harvested KICD corpus into `curriculum_chunk`.

    python -m app.ingest_curriculum                 normalise, embed, load
    python -m app.ingest_curriculum --no-embed      load rows only, no model download
    python -m app.ingest_curriculum --limit 50      a quick subset while developing
    python -m app.ingest_curriculum --path other.json

TRUNCATE AND LOAD, NOT UPSERT
-----------------------------
The harvested `id` field is not unique. It is built from the grade and the
subject slugged to eight characters, so Religious Education (CRE), (IRE) and
(HRE) all become "religiou", and Arabic, French and Mandarin all become
"foreignl". Measured on the corpus: 162 ids are shared by 213 rows, and
`g2_religiou_1` is simultaneously a CRE chunk about creation and an HRE chunk
about the school environment - different content under one identifier.
Narrowing the key to (grade, subject, id) does not fix it either; 76
collisions survive, because the three Foreign Languages designs share both the
subject and the slug.

Upserting on that identifier would therefore discard one row of each colliding
pair, silently and permanently. The corpus is derived data regenerated from
the JSON rather than anything a user has edited, so this replaces it wholesale
instead. Idempotency comes from "delete all, insert all", which needs no key
at all.

`source_row` records the record's index in the JSON file, which IS unique, so
any stored chunk can be traced back to the exact record it came from.

WHAT IS LEFT OUT
----------------
The JSON also carries 924 rubric rows, and they are not loaded.

The reason given here until 17 October was that the rows were unusable: that
all of them had only the `exceeds` descriptor, the extractor having shifted
the table columns by one. That was true of the v3 extraction and is no longer
true of the corpus this file reads. Measured against the current JSON, of 924
rows:

    four distinct level descriptions   873   (94.5%)
    all four levels identical            1
    partial, mostly missing `below`     50
    extraction_status OK               924

across six grades and thirteen subjects. So the rows are usable, and the
stated reason for leaving them out has expired. They are still not loaded,
but now for a different and much smaller reason: nothing reads them yet.
Loading them means a table, an embedding over the indicators, a retrieval
path and a prompt that can quote the descriptor for the learner's own tier -
a feature, with its own measurements, rather than a line in this function.

What has not changed is that the application's four KICD tiers come from
theta thresholds in code, so nothing downstream depends on these rows today.

The lesson worth keeping is about the comment rather than the rows: a
rationale recording a measurement goes stale when the measurement is
repaired, and a stale rationale reads exactly like a current one.

`strand_id` is left NULL. The application's `strand` rows are assessment
strands, seeded independently, and they do not correspond one-to-one with the
curriculum strand strings in this corpus. Retrieval filters on grade and
learning area, both of which are clean, and never on strand_id.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .curriculum import embedding_text, get_embedder, normalise, unmapped_private_use
from .db import ensure_extensions, get_engine, get_session_factory
from .models import Base, CurriculumChunk

DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "kicd" / "kicd_curriculum_chunks_full.json"
)
EMBED_BATCH = 64


def load_records(path: Path) -> list[dict]:
    """The `chunks` list from the harvested JSON, in file order."""
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    records = payload.get("chunks", [])
    if not records:
        raise SystemExit(f"{path} contains no 'chunks' list")
    return records


def to_chunk(record: dict, row: int) -> CurriculumChunk:
    """One harvested record as a CurriculumChunk, text repaired, not embedded."""
    return CurriculumChunk(
        source_id=record.get("id"),
        source_row=row,
        grade=record.get("grade"),
        learning_area=record.get("subject"),
        strand=normalise(record.get("strand")),
        sub_strand=normalise(record.get("sub_strand")),
        syllabus_text=normalise(record.get("text")),
        lessons=record.get("lessons"),
    )


def ingest(
    session: Session,
    records: list[dict],
    *,
    embed: bool = True,
    batch_size: int = EMBED_BATCH,
) -> dict:
    """Replace the corpus. Returns a summary for the caller to print."""
    leftovers: Counter[str] = Counter()
    for record in records:
        for field in ("text", "strand", "sub_strand"):
            leftovers += unmapped_private_use(record.get(field))

    skipped = [r for r in records if r.get("extraction_status") != "OK"]
    usable = [(i, r) for i, r in enumerate(records) if r.get("extraction_status") == "OK"]

    removed = session.execute(delete(CurriculumChunk)).rowcount
    chunks = [to_chunk(record, row) for row, record in usable]

    embedded = 0
    if embed and chunks:
        encode = get_embedder()
        for start in range(0, len(chunks), batch_size):
            window = chunks[start : start + batch_size]
            # The head, not the whole chunk - see curriculum.embedding_text.
            vectors = encode([embedding_text(c.syllabus_text) for c in window])
            for chunk, vector in zip(window, vectors, strict=True):
                chunk.embedding = vector
            embedded += len(window)
            print(f"  embedded {embedded}/{len(chunks)}", end="\r")
        print()

    session.add_all(chunks)
    session.commit()

    return {
        "removed": removed,
        "loaded": len(chunks),
        "skipped_not_ok": len(skipped),
        "embedded": embedded,
        "embedded_chars": sum(len(embedding_text(c.syllabus_text)) for c in chunks),
        "stored_chars": sum(len(c.syllabus_text) for c in chunks),
        "grades": sorted({c.grade for c in chunks if c.grade}),
        "learning_areas": len({c.learning_area for c in chunks if c.learning_area}),
        "unmapped_private_use": dict(leftovers),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", type=Path, default=DEFAULT_PATH)
    ap.add_argument("--limit", type=int, default=None, help="load only the first N records")
    ap.add_argument(
        "--no-embed",
        action="store_true",
        help="load the rows without embedding them (skips the model download)",
    )
    args = ap.parse_args()

    records = load_records(args.path)
    if args.limit:
        records = records[: args.limit]

    ensure_extensions()
    Base.metadata.create_all(get_engine())

    with get_session_factory()() as session:
        summary = ingest(session, records, embed=not args.no_embed)

    print(f"source: {args.path}")
    print(f"replaced {summary['removed']} existing chunks with {summary['loaded']}")
    print(f"embedded: {summary['embedded']}" + ("" if summary["embedded"] else "  (--no-embed)"))
    if summary["loaded"]:
        head = summary["embedded_chars"] / summary["loaded"]
        full = summary["stored_chars"] / summary["loaded"]
        print(
            f"mean chars: {head:.0f} embedded (the curriculum head) / "
            f"{full:.0f} stored and sent to the prompt"
        )
    print(f"grades: {', '.join(summary['grades'])}")
    print(f"learning areas: {summary['learning_areas']}")
    if summary["skipped_not_ok"]:
        print(f"skipped (extraction_status != OK): {summary['skipped_not_ok']}")
    if summary["unmapped_private_use"]:
        # Not fatal, but it means a KICD document used a glyph curriculum.py
        # has not been taught, and those characters were dropped.
        print("private-use codepoints with no repair mapping (dropped):")
        for code, count in sorted(summary["unmapped_private_use"].items()):
            print(f"  U+{ord(code):04X}  {count}")
    else:
        print("private-use codepoints with no repair mapping: none")


if __name__ == "__main__":
    main()
