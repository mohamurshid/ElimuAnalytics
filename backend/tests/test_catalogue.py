"""
Catalogue tests.

The cleaning rules are pinned against text copied from the real corpus,
because the corpus is what they exist for: a rule that passes a tidy
invented example and fails on "Environme nt" has not been tested.

The whole-corpus tests build the catalogue from the tracked corpus file,
normalised by the same function ingest uses, so they see what Postgres
holds. They pin exact counts on purpose: if re-extraction changes the
corpus, these fail and the catalogue gets looked at again, rather than
quietly changing what teachers can pick.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from app.catalogue import (
    GRADES,
    LEARNING_AREAS,
    Row,
    build,
    catalogue_rows,
    is_overview_row,
    join_split_words,
    split_number,
    strand_group,
    trim_name,
)
from app.curriculum import normalise
from app.db import get_session
from app.main import app
from app.models import Teacher
from app.security import create_token
from fastapi.testclient import TestClient
from sqlalchemy import select

from .test_repository import session  # noqa: F401 - pytest fixture

CORPUS = Path(__file__).resolve().parents[2] / "data" / "kicd" / "kicd_curriculum_chunks_full.json"


# --- the cleaning rules, on real text --------------------------------------
@pytest.mark.parametrize(
    "raw, number, rest_starts",
    [
        ("1.3.1 Insha ya Wasifu (Vipindi 2)", "1.3.1", "Insha"),
        ("10. 3 Grammar in Use", "10.3", "Grammar"),
        ("1.0 Whole Numbers", "1.0", "Whole"),
        ("Kusoma", None, "Kusoma"),
    ],
)
def test_section_numbers_are_split_off(raw, number, rest_starts):
    got_number, rest = split_number(raw)
    assert got_number == number
    assert rest.startswith(rest_starts)


@pytest.mark.parametrize(
    "rest, name",
    [
        # Content bled in, and the title repeated (Grade 5 Science, normalised)
        ("Classification of plants Classification of plants (flowering and "
         "non-flowering) • Uses of plants", "Classification of plants"),
        ("My purpose Talents and abilities 3 lessons", "My purpose Talents and abilities"),
        ("Insha ya Wasifu (Vipindi 2)", "Insha ya Wasifu"),
        ("Phonological awareness 1.2 Imitative speaking Basic greetings",
         "Phonological awareness"),
        ("Heat transfer", "Heat transfer"),
    ],
)
def test_bled_in_content_is_cut(rest, name):
    assert trim_name(rest) == name


def test_split_words_are_joined_only_when_one_half_is_not_a_word():
    vocab = Counter({"environment": 40, "environme": 1, "nt": 1,
                     "into": 30, "in": 900, "to": 800})
    assert join_split_words("Living things and their Environme nt", vocab) == (
        "Living things and their Environment"
    )
    # Both halves are words: left alone, however common the joined form.
    assert join_split_words("Moving in to class", vocab) == "Moving in to class"


def test_language_designs_group_by_the_strand_within_the_theme():
    assert strand_group("English", "4.2", "4.2.1") == "2"
    # Misnumbered heading: the sub-strand's own number wins.
    assert strand_group("English", "2.4", "2.1.1") == "1"
    # Sub-strand printed with two parts: the heading's second part is used.
    assert strand_group("Kiswahili", "8.1", "8.1") == "1"
    # Other designs group on the first part.
    assert strand_group("Mathematics", "2.0", "2.3") == "2"


def test_summary_table_rows_of_themed_designs_are_recognised():
    assert is_overview_row("English", "2.0", "2.1")
    assert not is_overview_row("English", "2.2", "2.2.1")
    assert not is_overview_row("Mathematics", "2.0", "2.1")


# --- the whole corpus ------------------------------------------------------
@pytest.fixture(scope="module")
def corpus_rows() -> list[Row]:
    records = json.loads(CORPUS.read_text(encoding="utf-8"))["chunks"]
    # source_row is the record's index in this file, as ingest stores it.
    return [
        Row(r["grade"], r["subject"], normalise(r["strand"]),
            normalise(r["sub_strand"]), normalise(r["text"]), source_row=i)
        for i, r in enumerate(records)
    ]


@pytest.fixture(scope="module")
def catalogue(corpus_rows):
    return build(corpus_rows)


def area(catalogue, grade, name):
    g = next(g for g in catalogue["grades"] if g["grade"] == grade)
    return next(a for a in g["learning_areas"] if a["learning_area"] == name)


def subs(a):
    return [s for strand in a["strands"] for s in strand["sub_strands"]]


def test_every_grade_lists_the_six_learning_areas(catalogue):
    assert [g["grade"] for g in catalogue["grades"]] == list(GRADES)
    for g in catalogue["grades"]:
        assert [a["learning_area"] for a in g["learning_areas"]] == list(LEARNING_AREAS)


def test_grade_6_english_is_listed_as_not_available(catalogue):
    """Its curriculum design was never harvested. Shown, not hidden."""
    english = area(catalogue, "Grade 6", "English")
    assert english["available"] is False
    assert english["strands"] == []
    available = sum(a["available"] for g in catalogue["grades"] for a in g["learning_areas"])
    assert available == 17


def test_every_row_in_scope_is_shown_or_counted(corpus_rows, catalogue):
    in_scope = [r for r in corpus_rows
                if r.grade in GRADES and r.learning_area in LEARNING_AREAS]
    shown = sum(s["chunks"] for g in catalogue["grades"]
                for a in g["learning_areas"] for s in subs(a))
    assert len(in_scope) == 448
    assert shown + catalogue["unplaced_rows"] == 448
    assert catalogue["unplaced_rows"] == 9


def test_the_strand_already_assessed_is_in_the_catalogue(catalogue):
    science = area(catalogue, "Grade 5", "Science and Technology")
    assert [s["name"] for s in science["strands"]] == [
        "Living things and their Environment", "Matter", "Force and Energy",
    ]
    heat = next(s for s in subs(science) if s["number"] == "3.3")
    assert heat["name"] == "Heat transfer"
    assert heat["key"] == "Grade 5|Science and Technology|3.0|3.3"


def test_themed_designs_give_four_strands_not_one_per_theme(catalogue):
    for grade, name in [("Grade 4", "English"), ("Grade 5", "English"),
                        ("Grade 4", "Kiswahili"), ("Grade 5", "Kiswahili"),
                        ("Grade 6", "Kiswahili")]:
        assert len(area(catalogue, grade, name)["strands"]) == 4, (grade, name)
    assert area(catalogue, "Grade 5", "Kiswahili")["language"] == "Kiswahili"
    assert area(catalogue, "Grade 5", "English")["language"] == "English"


def test_no_name_carries_extraction_debris(catalogue):
    for g in catalogue["grades"]:
        for a in g["learning_areas"]:
            for strand in a["strands"]:
                for text in [strand["name"]] + [s["name"] for s in strand["sub_strands"]]:
                    assert "•" not in text, text
                    assert "lessons" not in text.lower(), text
                    assert "vipindi" not in text.lower(), text
                    assert "Environme nt" not in text and "Langu age" not in text, text


def test_keys_are_unique(catalogue):
    keys = [s["key"] for g in catalogue["grades"]
            for a in g["learning_areas"] for s in subs(a)]
    assert len(keys) == len(set(keys))


# --- the endpoint ----------------------------------------------------------
@pytest.fixture
def client(session, corpus_rows):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[catalogue_rows] = lambda: corpus_rows
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def bearer(session) -> dict:  # noqa: F811
    t = session.scalar(select(Teacher))
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


def test_the_catalogue_needs_a_signed_in_teacher(client):
    assert client.get("/api/catalogue").status_code == 401


def test_the_catalogue_can_be_narrowed_to_one_grade(client, session):  # noqa: F811
    r = client.get("/api/catalogue", params={"grade": "Grade 5"}, headers=bearer(session))
    assert r.status_code == 200
    assert [g["grade"] for g in r.json()["grades"]] == ["Grade 5"]


def test_a_grade_outside_four_to_six_is_refused(client, session):  # noqa: F811
    r = client.get("/api/catalogue", params={"grade": "Grade 2"}, headers=bearer(session))
    assert r.status_code == 422
