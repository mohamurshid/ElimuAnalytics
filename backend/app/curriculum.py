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

WHAT GETS EMBEDDED IS NOT WHAT GETS STORED
------------------------------------------
all-MiniLM-L6-v2 truncates its input at 256 word-pieces and says nothing about
it. That was found by accident: after the v4 extractor lengthened every chunk
by 78%, five of the eight Grade 5 Science chunks came back with similarity
scores identical to four decimal places. An embedding is a function of its
input, so identical output means the model never saw the added text.

The damage was not the truncation itself - it was that the cut fell in
different places for different chunks. A chunk whose learning experiences ran
long lost its Values and Core competencies; a short one kept them.
Classification of plants rose from 0.0985 to 0.1269 and overtook Water
Pollution for no reason except that its boilerplate happened to fit. Ranking
was turning on chunk length.

So the split is now deliberate. `embedding_text()` returns the curriculum head
- strand, sub-strand, specific learning outcomes, suggested learning
experiences, key inquiry question - and that is what is embedded. The FULL
text, Projects and competencies and values and links included, is what is
stored and what goes into the report prompt.

The division matches what each half is for. Retrieval answers "which
sub-strand is this learner struggling with", which the head describes and the
trailing sections do not - they are near-identical boilerplate across
sub-strands and would blur exactly the distinctions retrieval depends on.
Generation answers "what should the teacher do", and that is the Projects,
which is why the v4 extractor had to recover them even though they never
reach a vector.
"""

from __future__ import annotations

import re
import threading
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

# Where the curriculum head ends and the trailing sections begin. These mirror
# CONTINUATION_LABELS in spike/build_curriculum_corpus.py, which is what put
# the trailing sections into the chunk to begin with. The duplication is
# deliberate - the backend does not import from the spike - but it means the
# two lists must change together, and test_curriculum.py pins the cut against
# a real chunk so drift fails a test rather than quietly degrading retrieval.
HEAD_ENDS_AT = re.compile(
    r"(?:^|[.;:?]\s+)("
    r"projects?\s*\d*\s*:"
    r"|core\s+competenc"
    r"|values\s*:"
    r"|pertinent\s+and\s+contemporary"
    r"|pcis\s*:?"
    r"|links?\s+to\s+other"
    r"|non[\s-]?formal"
    r"|suggested\s+resources"
    r"|community\s+service"
    r"|umilisi\b"
    r"|maadili\b"
    r"|masuala\s+mtambuko"
    r"|uhusiano\s+na\s+masomo"
    r"|miradi\b|mradi\b"
    r")",
    re.I,
)

Embedder = Callable[[Sequence[str]], list[list[float]]]

_embedder: Embedder | None = None

# Guards the lazy build below. The warm-up thread started at application
# startup and a request that arrives before it finishes would otherwise both
# construct a model, and the loser's 90MB of weights would sit in memory with
# nothing referencing them.
_embedder_lock = threading.Lock()


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


def embedding_text(text: str | None) -> str:
    """The part of a chunk that is embedded: the curriculum head.

    Everything from the first trailing-section label onwards is dropped. A
    chunk with no trailing sections is embedded whole.

    This does not guarantee the head fits in 256 word-pieces either - a long
    sub-strand can still be cut. What it guarantees is that every chunk is
    embedded on the same KIND of content, so a ranking cannot turn on whether
    a chunk's boilerplate happened to fit.
    """
    if not text:
        return ""
    match = HEAD_ENDS_AT.search(text)
    # start(1), not start(): the group begins at the label itself, so the
    # sentence punctuation preceding it stays with the head.
    return text[: match.start(1)].strip() if match else text.strip()


def set_embedder(embedder: Embedder | None) -> None:
    """Install an embedder, or pass None to fall back to the real model."""
    global _embedder
    _embedder = embedder


def get_embedder() -> Embedder:
    global _embedder
    # Checked once outside the lock so the warm path stays free, then again
    # inside it: by the time a waiter acquires the lock the model it was
    # waiting for usually exists.
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                _embedder = _load_sentence_transformer()
    return _embedder


def warm_embedder() -> None:
    """Build the model before anyone needs it.

    Measured on the development machine: 30.2 seconds to load, 0.14 seconds
    to encode once loaded. Paid lazily, those 30 seconds landed on the first
    report request of a worker's life - on top of a generation that already
    takes ten to thirty - and the dev proxy in front of Next closed the
    connection before the backend answered. The browser then showed a 500
    that no server had produced, and the second teacher to click never saw
    the fault at all.

    A no-op when an embedder is already installed, which is how the test
    suite stays model-free: the suite installs a stub, so warming finds one
    and returns.
    """
    if _embedder is None:
        get_embedder()


def _load_sentence_transformer() -> Embedder:
    # Imported here, not at module scope: see the note on laziness above.
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL)

    def encode(texts: Sequence[str]) -> list[list[float]]:
        return model.encode(list(texts), normalize_embeddings=True).tolist()

    return encode
