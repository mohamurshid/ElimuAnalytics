"""
Load the KICD rubric tables as assessment indicators.

    python -m app.ingest_rubrics            load or refresh every rubric row

The harvested corpus has carried these rows since it was built - 924 of them,
each an indicator with its four level descriptors - and nothing read them.
They are what the observation grid marks against.

A reload UPDATES rows in place, matched on `source_row`, and never deletes
one. Deleting would cascade to every level a teacher has recorded against
that indicator, which is the opposite of what refreshing the curriculum text
should do. A row that has vanished from the file simply stays.

The text is repaired with curriculum.normalise(), as the chunks are, because
the same PDFs produced it and the same private-use glyphs turn up in it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .curriculum import normalise
from .db import ensure_extensions, get_engine, get_session_factory
from .models import Base, RubricIndicator

DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "kicd" / "kicd_curriculum_chunks_full.json"
)
LEVEL_FIELDS = ("exceeds", "meets", "approaches", "below")


def load_rubrics(path: Path) -> list[dict]:
    """The `rubrics` list from the harvested JSON, in file order."""
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = payload.get("rubrics", [])
    if not rows:
        raise SystemExit(f"{path} contains no 'rubrics' list")
    return rows


def ingest(session: Session, rows: list[dict]) -> dict:
    """Insert new rows, refresh existing ones. Returns counts to print."""
    existing = {
        r.source_row: r
        for r in session.scalars(
            select(RubricIndicator).where(RubricIndicator.source == "kicd")
        )
    }
    added = updated = skipped = 0
    for row_no, row in enumerate(rows):
        indicator = normalise(row.get("indicator"))
        if row.get("extraction_status") != "OK" or not indicator:
            skipped += 1
            continue
        fields = {
            "grade": row.get("grade"),
            "learning_area": row.get("subject"),
            "indicator": indicator,
            **{f: normalise(row.get(f)) or None for f in LEVEL_FIELDS},
        }
        current = existing.get(row_no)
        if current is None:
            session.add(RubricIndicator(source="kicd", source_row=row_no, **fields))
            added += 1
        else:
            for name, value in fields.items():
                setattr(current, name, value)
            updated += 1
    session.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = ap.parse_args()

    rows = load_rubrics(args.path)
    ensure_extensions()
    # Creates the three observation tables on an existing database without a
    # reset, since create_all only adds what is missing.
    Base.metadata.create_all(get_engine())
    with get_session_factory()() as session:
        summary = ingest(session, rows)
    print(f"source: {args.path}")
    print(
        f"rubric indicators: {summary['added']} added, {summary['updated']} refreshed, "
        f"{summary['skipped']} skipped"
    )


if __name__ == "__main__":
    main()
