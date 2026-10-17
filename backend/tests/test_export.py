"""
PDF export tests: glyph coverage, the markdown subset, and the document.

No network, no database and no fixtures. The font is ReportLab's own, which
is the reason for choosing it: these run wherever the package is installed,
with nothing vendored into the repository and nothing fetched at test time.

The glyph tests are the point of the module. A missing glyph does not raise
in ReportLab - it draws a solid black box - so the only way a box is caught
before it reaches a parent is to ask the font, in a test, whether it can draw
what the pipeline produces.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from app import export

# What a real report contains: the bullet normalise() creates, the model's
# typographic quotes and dash, a degree sign and a fraction.
REPORT = (
    "**Paragraph 1: Current standing.** Chebet K. is rated “Below "
    "expectation” – and twelve items is enough to say so.\n\n"
    "• Modes of heat transfer\n"
    "• Good and poor conductors\n\n"
    "The project: “Learners to make oven gloves using locally available "
    "materials”. Water at 50°C, ½ a cup, 3² trials."
)

KISWAHILI = (
    "**Hali ya sasa:** Mwanafunzi yuko katika kiwango cha chini ya "
    "matarajio.\n\nMwalimu aeleze kondakta duni na kondakta mzuri."
)


def document(**overrides):
    fields = {
        "learner": "Chebet K.",
        "grade": "Grade 5",
        "school": "Test Primary School",
        "strand": "3.0 Force and Energy",
        "sub_strand": "3.3 Heat Transfer",
        "learning_area": "Science and Technology",
        "generated": datetime(2026, 10, 17, 13, 48, tzinfo=timezone.utc),
        "english": REPORT,
        "kiswahili": KISWAHILI,
    }
    return export.build_pdf(**{**fields, **overrides})


# --------------------------------------------------------------------------
# Glyphs
# --------------------------------------------------------------------------
def test_every_character_the_pipeline_produces_has_a_glyph():
    """The bullet matters most: normalise() creates it from the PUA repair."""
    assert export.glyphless(REPORT) == set()
    assert export.glyphless(KISWAHILI) == set()
    assert export.glyphless("• - – — … “”") == set()


def test_a_character_with_no_glyph_is_dropped_and_named():
    """Dropped beats drawn as a box, but silently dropped beats nothing."""
    text, dropped = export.printable("Maaŋaa")
    assert dropped == {"ŋ"}
    assert "ŋ" not in text


def test_a_known_gap_is_substituted_rather_than_dropped():
    text, dropped = export.printable("conduction → convection")
    assert dropped == set()
    assert "conduction -> convection" == text


def test_registering_the_font_twice_is_harmless():
    export.register_fonts()
    export.register_fonts()
    assert export.glyphless("a") == set()


# --------------------------------------------------------------------------
# The markdown subset
# --------------------------------------------------------------------------
def test_xml_is_escaped_before_bold_is_added():
    """The other order would escape the tags this function had just added."""
    assert export.markup("a & b <c>") == "a &amp; b &lt;c&gt;"
    assert export.markup("**only this**") == "<b>only this</b>"
    assert export.markup("**a & b**") == "<b>a &amp; b</b>"


def test_text_the_model_did_not_mark_up_is_left_alone():
    assert export.markup("2 * 3 and a ** b") == "2 * 3 and a ** b"


# --------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------
def test_the_document_is_a_pdf_and_nothing_was_dropped():
    doc = document()
    assert doc.pdf.startswith(b"%PDF")
    assert doc.dropped == set()


def text_of(pdf: bytes) -> str:
    """The document's own words, read back out of it.

    A size comparison was the first attempt at this and it was a bad proxy:
    an entire Kiswahili section changed the file by 139 bytes, because the
    embedded font dominates the size and the text is compressed. A test that
    can pass or fail for reasons unrelated to its claim is worse than no
    test, so this reads the page.
    """
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as document_:
        return "\n".join(page.extract_text() or "" for page in document_.pages)


def test_the_header_names_the_learner_and_the_sub_strand():
    page = text_of(document().pdf)

    assert "Chebet K." in page
    assert "Grade 5" in page
    assert "Test Primary School" in page
    assert "3.3 Heat Transfer" in page


def test_both_languages_are_on_the_page():
    page = text_of(document().pdf)

    assert "English" in page and "Kiswahili" in page
    # Single words, not phrases: extract_text keeps the line breaks, so any
    # phrase that happens to wrap would fail a substring match for reasons
    # that have nothing to do with the document being right.
    assert "gloves" in page          # the English half
    assert "kondakta" in page        # the Kiswahili half


def test_the_bold_markers_do_not_reach_the_page():
    """The model writes them; a parent should not have to read them."""
    page = text_of(document().pdf)

    assert "**" not in page
    assert "standing" in page


def test_the_page_carries_no_model_name_or_cost():
    """A parent-facing document, by the decision recorded in export.py."""
    page = text_of(document().pdf).lower()

    assert "claude" not in page
    assert "cents" not in page
    assert "token" not in page
    assert "exportable" not in page


def test_the_footer_says_it_is_not_a_grade():
    page = text_of(document().pdf)
    assert "ranking" in page
    assert "Curriculum Development" in page


def test_a_report_with_one_language_still_builds():
    assert document(english=None).pdf.startswith(b"%PDF")


def test_a_missing_date_or_learning_area_is_simply_absent():
    doc = document(generated=None, learning_area=None)
    assert doc.pdf.startswith(b"%PDF")
