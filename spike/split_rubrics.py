"""
Split the extracted corpus into curriculum chunks and assessment rubric rows.

KICD's rubric tables have the same five-column shape as the curriculum tables,
so the extractor accepted them as sub-strands: the indicator landed in `strand`,
the "exceeds expectation" descriptor landed in `sub_strand`, and the remaining
performance levels were mislabelled as learning outcomes and activities.

A curriculum row is identified by a numbered strand or sub-strand ("3.3 Heat
transfer"). Rubric rows are kept, not discarded: they carry KICD's own
four-level performance descriptors, which are the wording the report generator
should use when describing a learner's tier.

Run from the repo root:
    python spike\\split_rubrics.py
"""

import json
import re
from pathlib import Path

SRC = Path("data/kicd/kicd_curriculum_chunks_full.json")
NUMBERED = re.compile(r"^\s*\d+\.\d")

data = json.loads(SRC.read_text(encoding="utf-8"))
rows = data.get("chunks", [])

chunks, rubrics = [], []
for r in rows:
    if NUMBERED.match(r.get("strand", "")) or NUMBERED.match(r.get("sub_strand", "")):
        chunks.append(r)
    else:
        rubrics.append({
            "id": r["id"].replace("_", "_rub", 1),
            "grade": r["grade"],
            "subject": r["subject"],
            "indicator": r.get("strand", ""),
            "exceeds": r.get("sub_strand", ""),
            "meets": "",
            "approaches": "",
            "below": "",
            "raw_text": r.get("text", ""),
            "extraction_status": r.get("extraction_status", ""),
        })

data["chunks"] = chunks
data["rubrics"] = rubrics
SRC.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"curriculum chunks : {len(chunks)}")
print(f"rubric rows       : {len(rubrics)}")
print(f"written to {SRC}")

by_area = {}
for c in chunks:
    by_area[c["subject"]] = by_area.get(c["subject"], 0) + 1
print("\nCurriculum chunks by learning area:")
for a, n in sorted(by_area.items(), key=lambda kv: -kv[1]):
    print(f"  {n:5d}  {a}")