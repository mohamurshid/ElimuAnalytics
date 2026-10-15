"""
The curriculum corpus: text repair, and the sentence embedder.

Two jobs that both sit between the harvested KICD JSON and the
`curriculum_chunk` table.

TEXT REPAIR
-----------
The corpus was extracted from KICD's PDFs, and those PDFs draw their bullets
from the Symbol and Wingdings fonts. The glyphs survive extraction as Unicode
private-use codepoints, which have no meaning outside the font that drew them
and render as a box, a blank, or nothing at all depending on the reader.
Measured across the 1,617-chunk corpus: U+F0B7 appears 6,527 times, U+F0D8
fifty times, U+F02D eight, U+F09F five.

That matters more here than it would elsewhere. The report prompt requires the
KICD activity to be quoted VERBATIM, so whatever is stored is what a teacher
reads and what the grounding check compares a quotation against. Repairing the
text at render time instead would mean a rendered quote no longer matches the
stored chunk, and the grounding check would begin reporting genuine citations
as fabricated. So the repair happens once, on the way in.

What is deliberately NOT repaired:

  * Non-ASCII in general. The corpus legitimately contains Mandarin, French
    accents and IPA, because the Foreign Languages and English designs
    legitimately contain them. Stripping non-ASCII would delete the content of
    several learning areas outright.
  * U+25CF and U+2022, which are real, renderable bullets.
  * Words split by the PDF's line wrapping. "Living things and their
    Environme nt" is in the corpus and stays there: a mid-word space cannot be
    told from a real one without a dictionary, and guessing would corrupt
    Kiswahili and Mandarin far more often than it would fix English.

THE EMBEDDER
------------
all-MiniLM-L6-v2, 384 dimensions, which is where models.EMBEDDING_DIM comes
from. It is loaded lazily and can be replaced, for the same reason db.py
builds its engine lazily: importing a module in this package must not require
torch to be installed or a 90MB model to be downloaded. The tests substitute a
deterministic stand-in, so the suite stays offline.

Embeddings are stored as unit vectors, so pgvector's cosine-distance operator
and a plain dot product agree and a retrieval score means the same thing
wherever it is computed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence

EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Symbol and Wingdings list markers, as they survive PDF text extraction.
# Everything here was observed in the corpus; nothing is speculative.
PRIVATE_USE_REPAIRS = {
    "": "•",  # Symbol bullet
    "": "•",  # Wingdings arrowhead, used as a bullet
    "": "•",  # Wingdings box, used as a bullet
    "": "-",       # Symbol minus
}

PRIVATE_USE = re.compile(r"[-]")
_RUNS_OF_SPACE = re.compile(r"[ \t]{2,}")

Embedder = Callable[[Sequence[str]], list[list[float]]]

_embedder: Embedder | None = None


def normalise(text: str | None) -> str:
    """Repair extraction artefacts. Safe to call twice; the second call is a no-op."""
    if not text:
        return ""
    for broken, fixed in PRIVATE_USE_REPAIRS.items():
        text = text.replace(broken, fixed)
    # Anything still in the private-use area has no known mapping. Dropping it
    # beats storing a character that renders as a box in a report sent home,
    # but ingest reports what it dropped rather than doing it silently - see
    # unmapped_private_use below.
    text = PRIVATE_USE.sub("", text)
    return _RUNS_OF_SPACE.sub(" ", text).strip()


def unmapped_private_use(text: str | None) -> Counter[str]:
    """Private-use codepoints with no entry in PRIVATE_USE_REPAIRS.

    Called by ingest before normalise() discards them, so a KICD document
    using a glyph this module has not seen shows up as a number in the ingest
    summary instead of vanishing.
    """
    if not text:
        return Counter()
    for broken in PRIVATE_USE_REPAIRS:
        text = text.replace(broken, "")
    return Counter(PRIVATE_USE.findall(text))


def set_embedder(embedder: Embedder | None) -> None:
    """Install an embedder, or pass None to fall back to the real model."""
    global _embedder
    _embedder = embedder


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = _load_sentence_transformer()
    return _embedder


def _load_sentence_transformer() -> Embedder:
    # Imported here, not at module scope: see the note on laziness above.
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL)

    def encode(texts: Sequence[str]) -> list[list[float]]:
        return model.encode(list(texts), normalize_embeddings=True).tolist()

    return encode
