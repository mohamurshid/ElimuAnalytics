"""
Turning a finished report into a document a parent can read.

WHAT IS AND IS NOT ON THE PAGE
------------------------------
No theta, no item counts, no model name, no cost. A parent reading
"-1.74 (IRT theta)" learns nothing from it and may well read it as a mark out
of something; the KICD tier is the vocabulary the curriculum itself uses, and
the report's own first paragraph already states it in both languages.

The tier is not restated in a header either, and that is deliberate. The
`report` row does not store it, so a header would have to recompute it at
export time - from responses that may have changed since the report was
written - and a document that contradicts its own first paragraph is worse
than one that does not repeat it.

GLYPHS
------
ReportLab's built-in fonts are Type 1 with no glyph for most of Unicode, and
a missing glyph renders as a solid black box rather than failing. A box in a
document sent home is the exact failure `normalise()` exists to prevent at the
ingest end of this pipeline, so this module takes the same position: substitute
what can be substituted, drop what cannot, and report what was dropped instead
of doing it silently.

Vera ships inside ReportLab, so there is no font to vendor into a public
repository or download at runtime. Measured against it, Vera has a glyph for
every character the corpus produces after repair - the bullet and the hyphen -
as well as the typographic punctuation the model emits and Latin accents. It
has none for the arrow or for letters of some other African orthographies,
which is what the substitution table and the dropped set are for.

MARKDOWN
--------
The model writes `**Current standing.**` because it has been trained to, and
the prompt does not forbid it. On screen that prints as asterisks, which is
untidy; on a document going home it looks like a mistake. Bold markers are
converted and nothing else is, because every additional rule is a way for a
report's text to come out altered in a document nobody re-reads before
sending.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from datetime import datetime

FONT = "Vera"
FONT_BOLD = "Vera-Bold"

# Characters Vera has no glyph for, with an equivalent that means the same
# thing in a sentence. Anything missing and NOT listed here is dropped and
# named in `dropped`, which is the honest half of this arrangement.
SUBSTITUTIONS = {
    " ": " ",      # no-break space
    "→": "->",     # rightwards arrow
    "←": "<-",
    "′": "'",      # prime
    "″": '"',
}

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_PARAGRAPHS = re.compile(r"\n\s*\n")

_registered = False


def register_fonts() -> None:
    """Install Vera. Raises if ReportLab's own font is missing.

    Falling back to a built-in font would be the wrong kindness: it would
    produce a document with black boxes in it rather than an error a developer
    can act on, and the document is the thing that leaves the building.
    """
    global _registered
    if _registered:
        return

    import reportlab
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    folder = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    faces = {FONT: "Vera.ttf", FONT_BOLD: "VeraBd.ttf"}
    for name, filename in faces.items():
        path = os.path.join(folder, filename)
        if not os.path.exists(path):
            raise RuntimeError(
                f"{filename} is not in this ReportLab installation "
                f"({folder}), so no PDF can be produced with a font that "
                f"covers the report's characters."
            )
        pdfmetrics.registerFont(TTFont(name, path))

    # So that <b> inside a Paragraph resolves to the bold face rather than
    # being synthesised or ignored.
    addMapping(FONT, 0, 0, FONT)
    addMapping(FONT, 1, 0, FONT_BOLD)
    _registered = True


def glyphless(text: str) -> set[str]:
    """Which characters this font cannot draw."""
    register_fonts()
    from reportlab.pdfbase import pdfmetrics

    cmap = pdfmetrics.getFont(FONT).face.charToGlyph
    return {c for c in set(text) if ord(c) not in cmap and c not in "\n\r\t"}


def printable(text: str) -> tuple[str, set[str]]:
    """The text as it can be drawn, and what had to be removed to get there."""
    for original, replacement in SUBSTITUTIONS.items():
        text = text.replace(original, replacement)
    dropped = glyphless(text)
    for character in dropped:
        text = text.replace(character, "")
    return text, dropped


def markup(text: str) -> str:
    """Escape XML, then turn `**bold**` into ReportLab's own bold tag.

    Escaping first. Doing it the other way round would escape the tags this
    function has just added, and the reader would see them.
    """
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _BOLD.sub(r"<b>\1</b>", text)


@dataclass(frozen=True)
class Document:
    pdf: bytes
    # Characters that could not be drawn and were removed. Empty is the
    # expected case; anything in here is worth a look, because it means a
    # report went home with a character missing from a word.
    dropped: set[str]


def build_pdf(
    *,
    learner: str,
    grade: str,
    school: str,
    strand: str,
    sub_strand: str,
    learning_area: str | None,
    generated: datetime | None,
    english: str | None,
    kiswahili: str | None,
) -> Document:
    """One document, both languages, in the order the prompt generates them."""
    register_fonts()
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    dropped: set[str] = set()

    def clean(value: str) -> str:
        nonlocal dropped
        text, lost = printable(value)
        dropped |= lost
        return text

    title = ParagraphStyle(
        "title", fontName=FONT_BOLD, fontSize=15, leading=19, alignment=TA_LEFT
    )
    label = ParagraphStyle("label", fontName=FONT, fontSize=9.5, leading=13)
    heading = ParagraphStyle(
        "heading", fontName=FONT_BOLD, fontSize=12, leading=16, spaceBefore=10
    )
    body = ParagraphStyle(
        "body", fontName=FONT, fontSize=10.5, leading=15.5, spaceAfter=7
    )
    footer = ParagraphStyle("footer", fontName=FONT, fontSize=8.5, leading=12)

    story: list = [
        Paragraph(clean("Learning support report"), title),
        Spacer(1, 4 * mm),
        Paragraph(clean(f"<b>Learner:</b> {learner}"), label),
        Paragraph(clean(f"<b>Class:</b> {grade}"), label),
        Paragraph(clean(f"<b>School:</b> {school}"), label),
        Paragraph(clean(f"<b>Strand:</b> {strand}"), label),
        Paragraph(clean(f"<b>Sub-strand:</b> {sub_strand}"), label),
    ]
    if generated is not None:
        story.append(
            Paragraph(clean(f"<b>Date:</b> {generated.strftime('%d %B %Y')}"), label)
        )

    for language, content in (("English", english), ("Kiswahili", kiswahili)):
        if not content:
            continue
        story.append(Paragraph(clean(language), heading))
        for paragraph in _PARAGRAPHS.split(content.strip()):
            if paragraph.strip():
                story.append(Paragraph(markup(clean(paragraph.strip())), body))

    area = f" {learning_area}" if learning_area else ""
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            clean(
                f"Prepared from the Kenya Institute of Curriculum Development "
                f"{grade}{area} curriculum. This describes one sub-strand and "
                f"the next activity to try. It is not a mark, a grade or a "
                f"ranking against other learners."
            ),
            footer,
        )
    )

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=f"Learning support report - {learner}",
        author=school,
    ).build(story)
    return Document(pdf=buffer.getvalue(), dropped=dropped)
