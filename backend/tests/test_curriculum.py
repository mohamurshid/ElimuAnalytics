"""
Phase 5 corpus tests: text repair, embedder injection, and record mapping.

No database and no network. The curriculum_chunk table is excluded from the
SQLite test schema because pgvector has no SQLite equivalent (see
test_repository.py), so these exercise the pure functions and the mapping that
produces the ORM objects, not their persistence. Loading into Postgres is
checked by running the ingest script.

The embedder is never the real one here. all-MiniLM-L6-v2 is a 90MB download
and the suite has to run offline, which is why curriculum.py allows one to be
installed.
"""

from __future__ import annotations

import pytest
from app import curriculum
from app.ingest_curriculum import ingest, to_chunk


@pytest.fixture(autouse=True)
def _no_real_embedder():
    """Guarantee no test can reach for the real model, even by accident."""
    curriculum.set_embedder(lambda texts: [[0.0] * 384 for _ in texts])
    yield
    curriculum.set_embedder(None)


# --------------------------------------------------------------------------
# Text repair
# --------------------------------------------------------------------------
def test_symbol_font_bullet_becomes_a_real_bullet():
    # U+F0B7 occurs 6,527 times in the corpus and renders as a box or nothing.
    assert curriculum.normalise(" Modes of heat transfer") == "• Modes of heat transfer"


def test_every_observed_private_use_glyph_has_a_mapping():
    for broken, fixed in curriculum.PRIVATE_USE_REPAIRS.items():
        assert curriculum.normalise(f"a{broken}b") == f"a{fixed}b"


def test_unmapped_private_use_is_dropped_but_reported_first():
    text = "ab"  # not in the corpus, and not in the repair table
    assert curriculum.unmapped_private_use(text) == {"": 1}
    assert curriculum.normalise(text) == "ab"


def test_mapped_glyphs_are_not_reported_as_unmapped():
    assert curriculum.unmapped_private_use(" bullet") == {}


def test_legitimate_non_ascii_survives():
    """The regression that matters most.

    Stripping non-ASCII would be the obvious way to clean PDF text and would
    delete the content of several learning areas: the Mandarin designs are in
    Chinese, the French designs carry accents, and the English designs carry
    IPA. Kiswahili is the project's second report language.
    """
    for text in ("我是子", "élève à l'école", "/ɪ/ /ə/ /iː/", "Uhamishaji wa joto", "●", "•"):
        assert curriculum.normalise(text) == text


def test_split_words_are_left_alone():
    # "Environme nt" is in the corpus. A mid-word space cannot be told from a
    # real one without a dictionary, and guessing would corrupt Kiswahili and
    # Mandarin more often than it would fix English.
    assert curriculum.normalise("Living things and their Environme nt") == (
        "Living things and their Environme nt"
    )


def test_runs_of_space_collapse_and_edges_are_trimmed():
    assert curriculum.normalise("  3.3 Heat   transfer  \t ") == "3.3 Heat transfer"


def test_normalise_is_idempotent():
    once = curriculum.normalise("  Classify  conductors  good or poor")
    assert curriculum.normalise(once) == once


@pytest.mark.parametrize("value", [None, "", "   "])
def test_normalise_handles_nothing(value):
    assert curriculum.normalise(value) == ""


# --------------------------------------------------------------------------
# What gets embedded
# --------------------------------------------------------------------------
# The real Grade 5 Heat Transfer chunk as the v4 extractor produces it, cut
# down in the middle so the test stays readable. The head runs to the Key
# Inquiry Question; everything from "Project 1:" on is trailing content.
REAL_CHUNK = (
    "STRAND: 3.0 Force and Energy. SUB-STRAND: 3.3 Heat transfer (12 lessons). "
    "SPECIFIC LEARNING OUTCOMES: By the end of the sub strand the learner should be "
    "able to: a) demonstrate the modes of heat transfer in nature. "
    "SUGGESTED LEARNING EXPERIENCES: The learner is guided to: "
    "\u25cf carry out experiments to identify good and poor conductors of heat, "
    "KEY INQUIRY QUESTION: 1. How is heat transferred through materials in nature? "
    "Project 1: Learners to make oven gloves using locally available materials "
    "Project 2: Learners to make a fireless cooker "
    "Core competencies to be developed: Self-efficacy: The learner displays "
    "self-confidence. Values: Social justice: The learner shares resources."
)


def test_the_head_stops_where_the_trailing_sections_start():
    head = curriculum.embedding_text(REAL_CHUNK)
    assert head.endswith("How is heat transferred through materials in nature?")
    for gone in ("Project 1", "fireless cooker", "Core competencies", "Values:"):
        assert gone not in head
    for kept in ("STRAND:", "SPECIFIC LEARNING OUTCOMES:", "SUGGESTED LEARNING EXPERIENCES:"):
        assert kept in head


def test_the_full_text_is_what_is_stored_not_the_head():
    """The whole point of the split.

    The Projects must survive into the stored text, because that is what the
    report prompt quotes verbatim. They must NOT reach the embedding, because
    the trailing sections are boilerplate that blurs sub-strands.
    """
    chunk = to_chunk({**RECORD, "text": REAL_CHUNK}, 0)
    assert "fireless cooker" in chunk.syllabus_text
    assert "fireless cooker" not in curriculum.embedding_text(chunk.syllabus_text)


def test_a_chunk_with_no_trailing_sections_is_embedded_whole():
    plain = "STRAND: 1.0 Matter. SUB-STRAND: 1.1 Mixtures. KEY INQUIRY QUESTION: Why?"
    assert curriculum.embedding_text(plain) == plain


def test_the_kiswahili_labels_cut_too():
    # Kiswahili designs label the same sections in Kiswahili. Missing these
    # would embed 239 Kiswahili chunks on a different basis from the rest.
    text = "MADA: 1.0 Kusikiliza. Umilisi wa Kimsingi Unaokuzwa Mawasiliano na ushirikiano."
    head = curriculum.embedding_text(text)
    assert head == "MADA: 1.0 Kusikiliza."


@pytest.mark.parametrize("value", [None, "", "   "])
def test_embedding_text_handles_nothing(value):
    assert curriculum.embedding_text(value) == ""


def test_a_passing_mention_of_a_label_word_does_not_truncate():
    """"project" mid-sentence is not a section heading.

    Without the colon and the sentence-boundary guard, a learning experience
    reading "carry out a project to..." would cut the head in half and the
    chunk would be embedded on a fragment.
    """
    text = (
        "STRAND: 2.0 Matter. SUGGESTED LEARNING EXPERIENCES: learners carry out a "
        "project to separate mixtures and record their core competencies in a table."
    )
    assert curriculum.embedding_text(text) == text


def test_ingest_embeds_the_head_and_stores_the_whole_thing():
    seen: list[str] = []

    def spy(texts):
        seen.extend(texts)
        return [[0.0] * 384 for _ in texts]

    curriculum.set_embedder(spy)
    session = FakeSession()
    ingest(session, [{**RECORD, "text": REAL_CHUNK}])

    assert len(seen) == 1
    assert "Project 1" not in seen[0]
    assert "Project 1" in session.added[0].syllabus_text


# --------------------------------------------------------------------------
# Embedder injection
# --------------------------------------------------------------------------
def test_installed_embedder_is_used_and_can_be_replaced():
    curriculum.set_embedder(lambda texts: [[1.0, 2.0] for _ in texts])
    assert curriculum.get_embedder()(["a", "b"]) == [[1.0, 2.0], [1.0, 2.0]]


def test_clearing_the_embedder_does_not_load_the_model_until_asked():
    # set_embedder(None) must not itself trigger a 90MB download; the fallback
    # is lazy. Asserting the slot is empty is as far as this can go without
    # actually loading the model.
    curriculum.set_embedder(None)
    assert curriculum._embedder is None


# --------------------------------------------------------------------------
# Record -> chunk mapping
# --------------------------------------------------------------------------
RECORD = {
    "id": "g5_sciencea_14",
    "grade": "Grade 5",
    "subject": "Science and Technology",
    "strand": "3.0 Force and Energy",
    "sub_strand": "3.3 Heat transfer  Modes of heat transfer in nature",
    "lessons": 5,
    "text": "STRAND: 3.0 Force and Energy.  Classify conductors",
    "extraction_status": "OK",
}


def test_mapping_repairs_text_and_records_provenance():
    chunk = to_chunk(RECORD, 1416)
    assert chunk.source_id == "g5_sciencea_14"
    assert chunk.source_row == 1416
    assert chunk.grade == "Grade 5"
    assert chunk.learning_area == "Science and Technology"
    assert chunk.lessons == 5
    assert "" not in chunk.syllabus_text
    assert "" not in chunk.sub_strand
    assert chunk.syllabus_text == "STRAND: 3.0 Force and Energy. • Classify conductors"
    # Never guessed from the curriculum strand string.
    assert chunk.strand_id is None


def test_colliding_source_ids_both_survive():
    """The reason ingest truncates and reloads instead of upserting.

    g2_religiou_1 is a real example: the harvested id slugs the subject to
    eight characters, so this one identifier covers a CRE chunk about creation
    AND an HRE chunk about the school environment. Keying on it would discard
    one of them.
    """
    cre = {**RECORD, "id": "g2_religiou_1", "subject": "Religious Education (CRE)",
           "text": "Creation of the sky"}
    hre = {**RECORD, "id": "g2_religiou_1", "subject": "Religious Education (HRE)",
           "text": "Myself and School environment"}
    first, second = to_chunk(cre, 0), to_chunk(hre, 1)

    # chunk_id is a column default, assigned at flush, so it is None here -
    # uniqueness of the primary key is the database's job. What this test can
    # check is that nothing upstream of the insert merges the two records.
    assert first.source_id == second.source_id
    assert first.source_row != second.source_row
    assert first.syllabus_text != second.syllabus_text

    # And that ingest keeps both. A key-based upsert on source_id would leave
    # one row here, which is the whole reason it truncates and reloads.
    session = FakeSession()
    summary = ingest(session, [cre, hre], embed=False)
    assert summary["loaded"] == 2
    assert len(session.added) == 2
    assert {c.learning_area for c in session.added} == {
        "Religious Education (CRE)",
        "Religious Education (HRE)",
    }


# --------------------------------------------------------------------------
# ingest(), against a session that records what it was given
# --------------------------------------------------------------------------
class FakeResult:
    rowcount = 7


class FakeSession:
    def __init__(self):
        self.added: list = []
        self.commits = 0

    def execute(self, _statement):
        return FakeResult()

    def add_all(self, objects):
        self.added.extend(objects)

    def commit(self):
        self.commits += 1


def test_ingest_embeds_every_chunk_and_reports_what_it_replaced():
    session = FakeSession()
    summary = ingest(session, [RECORD, {**RECORD, "id": "g5_sciencea_13"}], batch_size=1)

    assert summary["removed"] == 7
    assert summary["loaded"] == 2
    assert summary["embedded"] == 2
    assert summary["grades"] == ["Grade 5"]
    assert session.commits == 1
    assert all(len(c.embedding) == 384 for c in session.added)


def test_ingest_without_embedding_leaves_the_vector_null():
    session = FakeSession()
    summary = ingest(session, [RECORD], embed=False)

    assert summary["embedded"] == 0
    assert session.added[0].embedding is None


def test_ingest_skips_records_the_extractor_could_not_parse():
    session = FakeSession()
    bad = {**RECORD, "extraction_status": "NO_STRUCTURE"}
    summary = ingest(session, [RECORD, bad], embed=False)

    assert summary["loaded"] == 1
    assert summary["skipped_not_ok"] == 1


def test_ingest_surfaces_unmapped_glyphs_in_the_summary():
    session = FakeSession()
    odd = {**RECORD, "text": "needs  a mapping"}
    summary = ingest(session, [odd], embed=False)

    assert summary["unmapped_private_use"] == {"": 1}
