"""
The curriculum catalogue: Grade -> learning area -> strand -> sub-strand.

What a teacher picks from when choosing what a class is assessed on, and what
question generation will be anchored to. Read-only and built from the
ingested corpus on every request; no table of its own.

Scope, decided 20 October: Grades 4-6 and six learning areas. Grades 1-3 wait
until after UAT (most learners cannot yet read a question). Foreign Languages
and the three Religious Education designs are left out because extraction
merged them - Arabic, French, German and Mandarin all arrive as one subject -
and Creative Arts because it is mostly practical work that multiple choice
does not test.

**Why this module cleans names at all.** `curriculum_chunk.strand` and
`sub_strand` are display text the extractor got wrong in three ways, all
measured against the corpus on 20 October:

  * content bleeding into the name ("1.1 Classification of plants
    Classification of plants (flowering ...") - cut at the first bullet,
    lesson count or following sub-strand number, then a repeated title
  * OCR splitting words ("Environme nt", "Langu age", "Govern ment") - joined
    where the corpus's own text shows the joined word is common and one half
    is not a word. On the Grades 4-6 core rows this made 11 joins, all
    correct, and no false ones
  * the same sub-strand under several spellings - merged by number, keeping
    the spelling with the fewest broken words

Names are cleaned on the way OUT. The stored text is left exactly as ingested,
because the report prompt quotes it and the grounding check compares against
it.

**Grouping is by structure, not by name.** Strand names vary within one
design ("Grammar in use", "Grammar in uses", "Grammar"; "Measurement" and
"Measurements"), so grouping on them splits strands apart. The numbering is
steadier. Most designs number sub-strands within strands - "2.3 Volume" is
in strand 2 - so they group on the first part. The English and Kiswahili
designs are organised by theme instead: "4.2.1" is theme 4, strand 2
(Reading), so they group on the second part, which gives four strands rather
than thirteen themes of four. Each group is shown under its most frequent
spelling.

**The key** identifies a sub-strand across requests, and is what a class will
be linked to: grade, learning area, strand number and sub-strand number. The
strand number is in it because the Grade 6 Kiswahili design numbers two
different sub-strands "1.3.1" (one under "1.3 Kuandika", one under "9.3
Kuandika").
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_teacher
from .db import get_session
from .models import CurriculumChunk, Teacher

router = APIRouter(prefix="/api", tags=["catalogue"])

GRADES = ("Grade 4", "Grade 5", "Grade 6")
LEARNING_AREAS = (
    "Mathematics",
    "Science and Technology",
    "English",
    "Kiswahili",
    "Social Studies",
    "Agriculture and Nutrition",
)
Grade = Literal["Grade 4", "Grade 5", "Grade 6"]

# A leading section number: "1.1", "1.3.1", "10. 3" (a stray space), "1.0".
_NUMBER = re.compile(r"^\s*(\d+(?:\s?\.\s?\d+)*)\.?\s*")
# Where a sub-strand name stops and bled-in content starts.
_NAME_ENDS = re.compile(
    r"[•●•\n]"
    r"|\(\s*\d+\s*(?:lessons?|vipindi)"
    r"|\(?\s*\b(?:lessons?|vipindi)\s*\d+"
    r"|\b\d+\s*(?:lessons?|vipindi)\b"
    r"|\s\d+\.\d+\s",
    re.I,
)
# Designs numbered theme.strand.sub-strand.
THEMED = ("English", "Kiswahili")
_WORD = re.compile(r"[A-Za-zÀ-ɏ']+")

# The OCR-join rule: the joined word must be common in the corpus text, and
# one half must be rare enough to be a fragment rather than a word.
JOINED_AT_LEAST = 5
FRAGMENT_AT_MOST = 2


@dataclass(frozen=True)
class Row:
    grade: str | None
    learning_area: str | None
    strand: str | None
    sub_strand: str | None
    syllabus_text: str = ""


def split_number(text: str | None) -> tuple[str | None, str]:
    """("1.3.1", "Insha ya Wasifu (Vipindi 2) ...") from the raw text."""
    text = (text or "").strip()
    m = _NUMBER.match(text)
    if not m:
        return None, text
    return re.sub(r"\s", "", m.group(1)), text[m.end():]


def trim_name(rest: str) -> str:
    """Cut bled-in content, then a title the extractor repeated."""
    cut = _NAME_ENDS.search(rest)
    name = (rest[: cut.start()] if cut else rest).strip(" .,:;-")
    words = name.split()
    for k in range(1, len(words) // 2 + 1):
        if [w.lower() for w in words[:k]] == [w.lower() for w in words[k : 2 * k]]:
            return " ".join(words[:k])
    return name


def vocabulary(texts: Iterable[str]) -> Counter[str]:
    return Counter(w.lower() for t in texts for w in _WORD.findall(t or ""))


def join_split_words(name: str, vocab: Counter[str]) -> str:
    """'Living things and their Environme nt' -> '... Environment'."""
    words = name.split(" ")
    out: list[str] = []
    i = 0
    while i < len(words):
        if i + 1 < len(words):
            a, b = words[i], words[i + 1]
            bare_b = b.rstrip(":,")
            if a.isalpha() and bare_b.isalpha():
                joined = (a + bare_b).lower()
                if (
                    vocab[joined] >= JOINED_AT_LEAST
                    and min(vocab[a.lower()], vocab[bare_b.lower()]) <= FRAGMENT_AT_MOST
                ):
                    out.append(a + b)
                    i += 2
                    continue
        out.append(words[i])
        i += 1
    return " ".join(out)


def strand_group(learning_area: str, strand_no: str | None, sub_no: str) -> str:
    """Which strand a sub-strand belongs to, from its numbering.

    For themed designs the sub-strand's own number is preferred when it has
    all three parts, because the strand heading is sometimes misnumbered
    ("2.4 Listening and Speaking" above "2.1.1"); otherwise the strand
    heading's second part is used ("8.1" above a sub-strand printed "8.1").
    """
    sub = sub_no.split(".")
    if learning_area in THEMED:
        if len(sub) >= 3:
            return sub[1]
        strand = (strand_no or "").split(".")
        if len(strand) >= 2:
            return strand[1]
        return sub[1] if len(sub) >= 2 else sub[0]
    return sub[0]


def is_overview_row(learning_area: str, strand_no: str | None, sub_no: str) -> bool:
    """A row from a themed design's summary table, not a teachable sub-strand.

    The English design opens with a table of strands and their parts:
    "2.0 Reading | 2.1 Intensive Reading 2.2 Extensive ...". Every part is
    taught again, in detail, inside a theme ("2.2.1 Intensive Reading: Oral
    Narrative ..."). Showing both would list each one twice.
    """
    if learning_area not in THEMED or not strand_no:
        return False
    return strand_no.split(".")[1:] == ["0"] and len(sub_no.split(".")) < 3


def _number_order(number: str | None) -> tuple:
    if not number:
        return (float("inf"),)
    return tuple(int(p) for p in number.split("."))


def _best_spelling(names: Counter[str]) -> str:
    """For a sub-strand: fewest spaces (an OCR split adds one), then most
    frequent."""
    return min(names, key=lambda n: (n.count(" "), -names[n]))


def _usual_spelling(names: Counter[str]) -> str:
    """For a strand: most frequent, so a truncated heading ("Natural and")
    seen once loses to the full one seen five times."""
    return min(names, key=lambda n: (-names[n], n.count(" ")))


@dataclass
class _Sub:
    strand_number: str | None
    number: str
    names: Counter = field(default_factory=Counter)
    chunks: int = 0


def build(rows: Iterable[Row]) -> dict:
    """The catalogue as plain data. Pure, so it is testable without Postgres."""
    rows = [
        r for r in rows if r.grade in GRADES and r.learning_area in LEARNING_AREAS
    ]
    vocab = vocabulary(r.syllabus_text for r in rows)

    def clean(text: str) -> str:
        return join_split_words(trim_name(text), vocab)

    # (grade, area) -> strand group -> sub key -> _Sub
    tree: dict = defaultdict(lambda: defaultdict(dict))
    group_names: dict = defaultdict(Counter)
    unnumbered: list[tuple[Row, str]] = []
    overview_rows = 0

    for r in rows:
        strand_no, strand_rest = split_number(r.strand)
        sub_no, sub_rest = split_number(r.sub_strand)
        sub_name = clean(sub_rest)
        if not sub_no:
            unnumbered.append((r, sub_name))
            continue
        if not sub_name:
            continue
        if is_overview_row(r.learning_area, strand_no, sub_no):
            overview_rows += 1
            continue
        group = strand_group(r.learning_area, strand_no, sub_no)
        group_name = clean(strand_rest)
        if group_name:
            group_names[(r.grade, r.learning_area, group)][group_name] += 1
        key = f"{r.grade}|{r.learning_area}|{strand_no or ''}|{sub_no}"
        sub = tree[(r.grade, r.learning_area)][group].setdefault(
            key, _Sub(strand_no, sub_no)
        )
        sub.names[sub_name] += 1
        sub.chunks += 1

    # A row with no sub-strand number is either a continuation of a numbered
    # sub-strand (same name) or extraction debris such as an assessment-method
    # list. The first is attached; the second is counted, not shown.
    unplaced = overview_rows
    for r, name in unnumbered:
        target = None
        for subs in tree[(r.grade, r.learning_area)].values():
            for sub in subs.values():
                if name and name.casefold() in {n.casefold() for n in sub.names}:
                    target = sub
        if target:
            target.chunks += 1
        else:
            unplaced += 1

    grades = []
    for grade in GRADES:
        areas = []
        for area in LEARNING_AREAS:
            groups = tree.get((grade, area), {})
            strands = []
            for group, subs in sorted(groups.items(), key=lambda kv: int(kv[0])):
                ordered = sorted(subs.items(), key=lambda kv: _number_order(kv[1].number))
                strands.append(
                    {
                        "name": _usual_spelling(group_names[(grade, area, group)])
                        if group_names[(grade, area, group)]
                        else f"Strand {group}",
                        "sub_strands": [
                            {
                                "key": key,
                                "number": sub.number,
                                "name": _best_spelling(sub.names),
                                "chunks": sub.chunks,
                            }
                            for key, sub in ordered
                        ],
                    }
                )
            areas.append(
                {
                    "learning_area": area,
                    # Questions are written in the language of the learning
                    # area: Kiswahili for Kiswahili, otherwise English.
                    "language": "Kiswahili" if area == "Kiswahili" else "English",
                    "available": bool(strands),
                    "strands": strands,
                }
            )
        grades.append({"grade": grade, "learning_areas": areas})
    return {"grades": grades, "unplaced_rows": unplaced}


@dataclass(frozen=True)
class Entry:
    """One sub-strand, with what a Strand row needs to be made from it."""

    key: str
    grade: str
    learning_area: str
    strand: str
    number: str
    name: str

    @property
    def strand_name(self) -> str:
        """The Strand.name format reports split on: "<strand> / <sub-strand>"."""
        return f"{self.strand} / {self.number} {self.name}"


def lookup(rows: Iterable[Row], key: str) -> Entry | None:
    """The catalogue entry for a key, or None if the catalogue has no such
    sub-strand - which is how a key typed by hand, or one from a corpus that
    has since been re-extracted, is refused."""
    for grade in build(rows)["grades"]:
        for area in grade["learning_areas"]:
            for strand in area["strands"]:
                for sub in strand["sub_strands"]:
                    if sub["key"] == key:
                        return Entry(
                            key=key,
                            grade=grade["grade"],
                            learning_area=area["learning_area"],
                            strand=strand["name"],
                            number=sub["number"],
                            name=sub["name"],
                        )
    return None


# --- endpoint --------------------------------------------------------------
class SubStrandOut(BaseModel):
    key: str
    number: str
    name: str
    chunks: int


class CatalogueStrandOut(BaseModel):
    name: str
    sub_strands: list[SubStrandOut]


class LearningAreaOut(BaseModel):
    learning_area: str
    language: str
    # False when the corpus has nothing for this area in this grade - Grade 6
    # English, whose curriculum design was never harvested. Listed rather than
    # omitted so the picker can say so instead of looking incomplete.
    available: bool
    strands: list[CatalogueStrandOut]


class GradeOut(BaseModel):
    grade: str
    learning_areas: list[LearningAreaOut]


class CatalogueOut(BaseModel):
    grades: list[GradeOut]
    # Rows not shown: extraction debris with no sub-strand number, and the
    # summary-table rows of themed designs. Reported, so a change in the
    # corpus shows up as a number rather than vanishing.
    unplaced_rows: int


def catalogue_rows(session: Session = Depends(get_session)) -> list[Row]:
    """The rows `build` needs. A dependency so tests can supply the corpus
    without Postgres - the chunk table carries a pgvector column that the
    SQLite test database cannot create."""
    result = session.execute(
        select(
            CurriculumChunk.grade,
            CurriculumChunk.learning_area,
            CurriculumChunk.strand,
            CurriculumChunk.sub_strand,
            CurriculumChunk.syllabus_text,
        ).where(
            CurriculumChunk.grade.in_(GRADES),
            CurriculumChunk.learning_area.in_(LEARNING_AREAS),
        )
    )
    return [Row(*r) for r in result]


@router.get("/catalogue", response_model=CatalogueOut)
def get_catalogue(
    grade: Grade | None = Query(default=None),
    rows: list[Row] = Depends(catalogue_rows),
    _: Teacher = Depends(current_teacher),
) -> dict:
    """Curriculum-wide, like strands, so not scoped to a school."""
    catalogue = build(rows)
    if grade:
        catalogue["grades"] = [g for g in catalogue["grades"] if g["grade"] == grade]
    return catalogue
