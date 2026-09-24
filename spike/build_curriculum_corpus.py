"""
Build the full KICD curriculum corpus: Grades 1-6, every learning area.

Extends the Day 4 spike from 8 hand-extracted chunks (Grade 5 Science) to the
whole Lower and Upper Primary curriculum, so that Chapter 1's scope claim
matches what the system actually ingests.

THREE STAGES, runnable separately so each can be checked before the next.

  1. discover  Enumerate PDFs via the WordPress media API on cbcelimu.com and
               write manifest.json. Downloads nothing. Filenames on that site
               are irregular (GRADE.5.SCIENCE.pdf exists, GRADE.5.MATHEMATICS.pdf
               does not), so URLs are enumerated, never guessed.
  2. download  Fetch each PDF in the manifest, skipping files already on disk.
  3. extract   Parse each PDF into curriculum chunks and write a coverage report.

USAGE
  pip install pdfplumber
  python build_curriculum_corpus.py --discover
  python build_curriculum_corpus.py --download
  python build_curriculum_corpus.py --extract
  python build_curriculum_corpus.py --all

  --grades 4,5,6      restrict to certain grades
  --limit 5           stop after N files (use this first)
  --outdir data/kicd  where PDFs and outputs go

WHAT TO WATCH FOR
  Day 4 proved that *Science* designs extract cleanly with no OCR. It proved
  nothing about Kiswahili, Creative Arts or Indigenous Language, which use
  different table layouts. The coverage report flags every file whose structure
  did not parse, so that assumption is tested rather than inherited.

  Any file marked NEEDS_OCR or NO_STRUCTURE needs a look before its chunks are
  trusted. Chunks from those files are still written, but tagged.

Manual additions: put one URL per line in extra_urls.txt next to this script
(for example Google Drive `uc?export=download` links for anything cbcelimu is
missing) and they are merged into the manifest during discovery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

VERSION = "v3 (separates curriculum rows from assessment rubric rows)"

MEDIA_API = "https://cbcelimu.com/wp-json/wp/v2/media"
USER_AGENT = "Mozilla/5.0 (compatible; ElimuAnalytics-Research/1.0; academic use)"
POLITE_DELAY = 1.0  # seconds between requests - do not hammer a free resource

# Learning areas across Lower Primary (Grades 1-3) and Upper Primary (4-6).
# Keys are canonical names; values are tokens that may appear in a filename.
LEARNING_AREAS = {
    "Mathematics": ["MATHEMATIC", "MATHS", "MATH"],
    "English": ["ENGLISH"],
    "Kiswahili": ["KISWAHILI", "KISW"],
    "Science and Technology": ["SCIENCE", "SCI.TECH", "SCIENCE.TECHNOLOGY"],
    "Agriculture and Nutrition": ["AGRICULTURE", "AGRIC", "NUTRITION"],
    "Social Studies": ["SOCIAL"],
    "Creative Arts": ["CREATIVE", "ART.CRAFT", "MUSIC"],
    "Religious Education (CRE)": ["CRE", "CHRISTIAN"],
    "Religious Education (IRE)": ["IRE", "ISLAMIC"],
    "Religious Education (HRE)": ["HRE", "HINDU"],
    "Indigenous Language": ["INDIGENOUS"],
    "Environmental Activities": ["ENVIRONMENT"],
    "Literacy": ["LITERACY"],
    "Hygiene and Nutrition": ["HYGIENE"],
    "Movement and Creative Activities": ["MOVEMENT"],
    "Physical and Health Education": ["PHYSICAL", "HEALTH.EDUCATION"],
    "Pre-Technical Studies": ["PRE.TECHNICAL", "PRETECHNICAL"],
    "Foreign Languages": ["FRENCH", "GERMAN", "MANDARIN", "ARABIC"],
}

# Filenames containing these are assessment papers, not curriculum designs.
EXCLUDE_TOKENS = [
    "SBA", "QUESTION", "MARKING", "MWONGOZO", "NAKALA", "SEHEMU", "ANSWER",
    "MARKING-SCHEME", "MARKINGSCHEME", "ASSESSMENT", "EXAM", "TERM", "REPORT-FORM",
    "LEARNERS-COPY", "TEACHERS-COPY", "SET-", "SCHEME", "NOTES", "HOLIDAY",
    "REVISION", "PP1", "PP2",
]

# KICD section headings, as they appear in the designs.
SECTION_PATTERNS = {
    "outcomes": re.compile(r"SPECIFIC\s+LEARNING\s+OUTCOMES?", re.I),
    "experiences": re.compile(r"SUGGESTED\s+LEARNING\s+EXPERIENCES?", re.I),
    "inquiry": re.compile(r"KEY\s+INQUIRY\s+QUESTIONS?", re.I),
    "strand": re.compile(r"\bSTRAND\b", re.I),
    "substrand": re.compile(r"SUB[\s.\-]?STRAND", re.I),
}

LESSON_RE = re.compile(r"\((\d{1,3})\s*lessons?\)", re.I)
GRADE_RE = re.compile(r"GRADE[\s._\-]*([1-9])", re.I)


# ---------------------------------------------------------------------------
# Stage 1: discover
# ---------------------------------------------------------------------------
def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def classify(filename: str):
    """Return (grade, learning_area) or (None, None) if this is not a design."""
    upper = filename.upper()

    for bad in EXCLUDE_TOKENS:
        if bad in upper:
            return None, None

    m = GRADE_RE.search(upper)
    if not m:
        return None, None
    grade = int(m.group(1))
    if grade > 6:
        return None, None

    for area, tokens in LEARNING_AREAS.items():
        for tok in tokens:
            if tok in upper:
                return grade, area
    return grade, "Unclassified"


def discover(outdir: Path, grades: set[int]) -> list[dict]:
    print("Enumerating media on cbcelimu.com ...")
    found, page, seen = [], 1, set()

    while True:
        url = f"{MEDIA_API}?per_page=100&page={page}&mime_type=application/pdf"
        try:
            batch = fetch_json(url)
        except Exception as exc:  # noqa: BLE001 - any failure ends paging
            print(f"  page {page}: stopped ({exc})")
            break
        if not batch:
            break

        for item in batch:
            src = item.get("source_url", "")
            if not src.lower().endswith(".pdf") or src in seen:
                continue
            seen.add(src)
            name = src.rsplit("/", 1)[-1]
            grade, area = classify(name)
            if grade is None or grade not in grades:
                continue
            found.append(
                {
                    "url": src,
                    "filename": name,
                    "grade": grade,
                    "learning_area": area,
                    "source": "cbcelimu",
                }
            )

        print(f"  page {page}: {len(batch)} files scanned, {len(found)} designs so far")
        page += 1
        time.sleep(POLITE_DELAY)
        if page > 40:  # hard stop
            break

    extra = Path(__file__).with_name("extra_urls.txt")
    if extra.exists():
        for line in extra.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Accept either "URL" or "URL | GRADE.5.MATHEMATICS.pdf".
            # The filename form is needed for Google Drive links, whose URLs
            # carry no name - without it every one of them lands as "uc.pdf"
            # and they overwrite each other.
            if "|" in line:
                url, name = (p.strip() for p in line.split("|", 1))
            else:
                url = line
                name = url.rsplit("/", 1)[-1].split("?")[0] or "manual.pdf"
            if not name.lower().endswith(".pdf"):
                name = f"{name}.pdf"
            grade, area = classify(name)
            found.append(
                {
                    "url": url,
                    "filename": name,
                    "grade": grade or 0,
                    "learning_area": area or "Unclassified",
                    "source": "manual",
                }
            )
        print(f"  merged {len(found)} total after extra_urls.txt")

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "manifest.json").write_text(
        json.dumps(found, indent=2), encoding="utf-8"
    )

    print(f"\nDiscovered {len(found)} candidate curriculum designs.\n")
    grid = defaultdict(list)
    for f in found:
        grid[f["grade"]].append(f["learning_area"])
    for g in sorted(grid):
        areas = sorted(set(grid[g]))
        print(f"  Grade {g}: {len(grid[g])} files -> {', '.join(areas)}")

    missing = []
    for g in sorted(grades):
        have = {f["learning_area"] for f in found if f["grade"] == g}
        if not have:
            missing.append(f"Grade {g}: nothing found")
    if missing:
        print("\nGaps:")
        for m in missing:
            print(f"  {m}")
        print("  Add direct URLs to extra_urls.txt and re-run --discover.")

    print(f"\nManifest written to {outdir / 'manifest.json'}")
    return found


# ---------------------------------------------------------------------------
# Stage 2: download
# ---------------------------------------------------------------------------
def download(outdir: Path, limit: int | None) -> None:
    manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    pdf_dir = outdir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    todo = manifest[:limit] if limit else manifest
    ok = skipped = failed = 0

    for i, entry in enumerate(todo, 1):
        dest = pdf_dir / entry["filename"]
        if dest.exists() and dest.stat().st_size > 10_000:
            skipped += 1
            continue
        try:
            req = urllib.request.Request(
                entry["url"], headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if not data.startswith(b"%PDF"):
                print(f"  [{i}/{len(todo)}] NOT A PDF: {entry['filename']}")
                failed += 1
                continue
            dest.write_bytes(data)
            ok += 1
            print(f"  [{i}/{len(todo)}] {entry['filename']} ({len(data)//1024} KB)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [{i}/{len(todo)}] FAILED {entry['filename']}: {exc}")
        time.sleep(POLITE_DELAY)

    print(f"\nDownloaded {ok}, skipped {skipped} already present, {failed} failed.")
    print(f"PDFs in {pdf_dir}")


# ---------------------------------------------------------------------------
# Stage 3: extract
# ---------------------------------------------------------------------------
def clean(cell) -> str:
    if not cell:
        return ""
    return re.sub(r"\s+", " ", str(cell)).strip()


# A curriculum row is identified by a numbered strand or sub-strand
# ("3.3 Heat transfer"). KICD's assessment rubric tables have the same column
# count, so without this test they parse as sub-strands: the indicator lands in
# `strand`, the "exceeds expectation" descriptor lands in `sub_strand`, and the
# remaining performance levels are mislabelled as learning outcomes and
# activities. In the first full run that produced 923 fake sub-strands out of
# 2,540 chunks - 64% of Mathematics, 67% of Social Studies.
NUMBERED_RE = re.compile(r"^\s*\d+\.\d")


def parse_row(cells: list[str], grade: int, area: str, index: int):
    """Classify one table row and return ("curriculum"|"rubric", record).

    KICD curriculum rows run: Strand | Sub Strand | Specific Learning Outcomes |
    Suggested Learning Experiences | Key Inquiry Question(s).
    KICD rubric rows run: Indicator | Exceeds | Meets | Approaches | Below.

    Both are five columns of prose, so the numbering test is what separates
    them. Rubric rows are kept rather than discarded - they carry KICD's own
    four-level performance descriptors, which are exactly the wording the
    report generator should use when describing a learner's tier.
    """
    cells = [clean(c) for c in cells]
    if len(cells) < 4:
        return None
    body = " ".join(cells)
    if len(body) < 200:  # header rows and page furniture
        return None

    strand, sub_strand = cells[0], cells[1]
    if not strand or not sub_strand:
        return None
    if SECTION_PATTERNS["outcomes"].search(strand):  # this row IS the header
        return None

    if not (NUMBERED_RE.match(strand) or NUMBERED_RE.match(sub_strand)):
        levels = (cells + ["", "", "", ""])[1:5]
        return (
            "rubric",
            {
                "id": f"g{grade}_{re.sub(r'[^a-z]', '', area.lower())[:8]}_rub{index}",
                "grade": f"Grade {grade}",
                "subject": area,
                "indicator": strand,
                "exceeds": levels[0],
                "meets": levels[1],
                "approaches": levels[2],
                "below": levels[3],
                "text": (
                    f"INDICATOR: {strand}. EXCEEDS EXPECTATION: {levels[0]} "
                    f"MEETS EXPECTATION: {levels[1]} "
                    f"APPROACHES EXPECTATION: {levels[2]} "
                    f"BELOW EXPECTATION: {levels[3]}"
                ),
            },
        )

    # The lesson count usually sits inside the sub-strand cell. Pull it out into
    # its own field and strip it from the label, so the chunk matches the Day 4
    # format (clean sub_strand, separate `lessons`) and the count is not printed
    # twice in the chunk text.
    lessons = None
    m = LESSON_RE.search(" ".join(cells[:2]))
    if m:
        lessons = int(m.group(1))
    strand = LESSON_RE.sub("", strand).strip(" .;,")
    sub_strand = LESSON_RE.sub("", sub_strand).strip(" .;,")
    if not sub_strand:
        return None

    outcomes = cells[2] if len(cells) > 2 else ""
    experiences = cells[3] if len(cells) > 3 else ""
    inquiry = cells[4] if len(cells) > 4 else ""

    text = (
        f"STRAND: {strand}. SUB-STRAND: {sub_strand}"
        + (f" ({lessons} lessons)" if lessons else "")
        + ". SPECIFIC LEARNING OUTCOMES: "
        + outcomes
        + " SUGGESTED LEARNING EXPERIENCES: "
        + experiences
        + (f" KEY INQUIRY QUESTION: {inquiry}" if inquiry else "")
    )

    return (
        "curriculum",
        {
            "id": f"g{grade}_{re.sub(r'[^a-z]', '', area.lower())[:8]}_{index}",
            "grade": f"Grade {grade}",
            "subject": area,
            "strand": strand,
            "sub_strand": sub_strand,
            "lessons": lessons,
            "text": re.sub(r"\s+", " ", text).strip(),
        },
    )


def extract_one(path: Path, grade: int, area: str):
    import pdfplumber

    chunks: list[dict] = []
    rubrics: list[dict] = []
    pages = chars = tables = 0

    page_errors = 0

    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        for page in pdf.pages:
            # One malformed page must not cost the whole document. Grade.2.KISWAHILI
            # raised "argument out of range" from pdfminer and lost 59 pages of
            # usable curriculum; now only the bad page is skipped.
            try:
                text = page.extract_text() or ""
                chars += len(text)
                for table in page.extract_tables() or []:
                    tables += 1
                    for row in table:
                        parsed = parse_row(
                            row, grade, area, len(chunks) + len(rubrics) + 1
                        )
                        if not parsed:
                            continue
                        kind, record = parsed
                        (chunks if kind == "curriculum" else rubrics).append(record)
            except Exception:  # noqa: BLE001 - pdfminer raises many shapes
                page_errors += 1
                continue

    chars_per_page = chars / pages if pages else 0
    if chars_per_page < 100:
        status = "NEEDS_OCR"
    elif not chunks:
        status = "NO_STRUCTURE"
    elif page_errors:
        status = "PARTIAL"
    elif len(chunks) < 3:
        status = "THIN"
    else:
        status = "OK"

    stats = {
        "file": path.name,
        "grade": grade,
        "learning_area": area,
        "pages": pages,
        "chars_per_page": round(chars_per_page),
        "tables": tables,
        "chunks": len(chunks),
        "rubrics": len(rubrics),
        "page_errors": page_errors,
        "status": status,
    }
    for c in chunks:
        c["extraction_status"] = status
    for r in rubrics:
        r["extraction_status"] = status
    return chunks, rubrics, stats


def extract(outdir: Path, limit: int | None) -> None:
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        sys.exit("pdfplumber is not installed. Run: pip install pdfplumber")

    manifest = {
        e["filename"]: e
        for e in json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    }
    pdf_dir = outdir / "pdfs"
    # WordPress re-uploads the same design under a "-1" suffix, and those copies
    # put near-identical competitors into the retrieval pool, quietly distorting
    # any accuracy figure measured against it.
    #
    # v2.1: deduplicate on FILE CONTENT, not on the filename stem. The stem rule
    # stripped any trailing "-N", so "Environmental-Activities-for-Grade-3"
    # collapsed onto "...-for-Grade-2" and a whole learning area was silently
    # dropped. Hashing compares what the files actually contain, and cannot
    # confuse a grade number for a re-upload counter.
    by_hash: dict[str, Path] = {}
    dup_files: list[str] = []
    for path in sorted(pdf_dir.glob("*.pdf")):
        digest = hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 - not security
        if digest in by_hash:
            # Keep whichever name is shorter: "X.pdf" over "X-1.pdf".
            keep, drop = sorted([by_hash[digest], path], key=lambda p: len(p.name))
            by_hash[digest] = keep
            dup_files.append(drop.name)
        else:
            by_hash[digest] = path

    files = sorted(by_hash.values())
    if dup_files:
        print(f"Skipping {len(dup_files)} duplicate re-uploads: "
              f"{', '.join(sorted(dup_files)[:4])}"
              f"{' ...' if len(dup_files) > 4 else ''}\n")
    if limit:
        files = files[:limit]
    if not files:
        sys.exit(f"No PDFs in {pdf_dir}. Run --download first.")

    all_chunks: list[dict] = []
    all_rubrics: list[dict] = []
    all_stats: list[dict] = []

    for i, path in enumerate(files, 1):
        entry = manifest.get(path.name, {})
        grade = entry.get("grade", 0)
        area = entry.get("learning_area", "Unclassified")
        try:
            chunks, rubrics, stats = extract_one(path, grade, area)
        except Exception as exc:  # noqa: BLE001
            stats = {
                "file": path.name, "grade": grade, "learning_area": area,
                "pages": 0, "chars_per_page": 0, "tables": 0, "chunks": 0,
                "rubrics": 0, "status": f"FAILED: {exc}",
            }
            chunks, rubrics = [], []
        all_chunks.extend(chunks)
        all_rubrics.extend(rubrics)
        all_stats.append(stats)
        print(f"  [{i}/{len(files)}] {path.name:<50} {stats['status']:<13} "
              f"{stats['chunks']:>4} chunks  {stats.get('rubrics', 0):>4} rubrics")

    # Second dedup pass, on text. Catches the same row appearing in two
    # differently-named files, which filename matching cannot see.
    def dedupe(records: list[dict]) -> tuple[list[dict], int]:
        seen: set[str] = set()
        out: list[dict] = []
        for r in records:
            key = re.sub(r"\W+", "", r["text"].lower())[:400]
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out, len(records) - len(out)

    all_chunks, dup_chunks = dedupe(all_chunks)
    all_rubrics, dup_rubrics = dedupe(all_rubrics)
    if dup_chunks or dup_rubrics:
        print(f"\nRemoved {dup_chunks} duplicate chunks and "
              f"{dup_rubrics} duplicate rubric rows by content.")

    out_json = outdir / "kicd_curriculum_chunks_full.json"
    out_json.write_text(
        json.dumps(
            {
                "source": "KICD Curriculum Designs (Rationalised, Revised 2024)",
                "harvested_from": "cbcelimu.com",
                "rubric_levels": [
                    "Exceeds expectation", "Meets expectation",
                    "Approaches expectation", "Below expectation",
                ],
                "chunks": all_chunks,
                "rubrics": all_rubrics,
            },
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Coverage report
    status_counts = Counter(s["status"].split(":")[0] for s in all_stats)
    by_grade = defaultdict(lambda: {"files": 0, "chunks": 0, "areas": set()})
    for s in all_stats:
        g = by_grade[s["grade"]]
        g["files"] += 1
        g["chunks"] += s["chunks"]
        g["areas"].add(s["learning_area"])

    lines = ["# KICD curriculum corpus — coverage report", ""]
    lines.append(f"- Files processed: **{len(all_stats)}**")
    lines.append(f"- Curriculum sub-strand chunks: **{len(all_chunks)}**")
    lines.append(f"- Assessment rubric rows: **{len(all_rubrics)}**")
    lines.append("")
    lines.append("## Extraction status")
    lines.append("")
    lines.append("| Status | Files | Meaning |")
    lines.append("|---|---|---|")
    meanings = {
        "OK": "Parsed cleanly, structure detected",
        "THIN": "Parsed, but suspiciously few chunks — check the layout",
        "NO_STRUCTURE": "Text extracted but no curriculum rows found — different table layout",
        "NEEDS_OCR": "Little or no selectable text — scanned document",
        "FAILED": "Extraction raised an error",
    }
    for st, n in status_counts.most_common():
        lines.append(f"| {st} | {n} | {meanings.get(st, '')} |")
    lines.append("")
    lines.append("## Coverage by grade")
    lines.append("")
    lines.append("| Grade | Files | Learning areas | Chunks |")
    lines.append("|---|---|---|---|")
    for g in sorted(by_grade):
        d = by_grade[g]
        lines.append(f"| {g} | {d['files']} | {len(d['areas'])} | {d['chunks']} |")
    lines.append("")
    lines.append("## Per file")
    lines.append("")
    lines.append("| File | Grade | Learning area | Pages | Chars/page | Chunks | Status |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in sorted(all_stats, key=lambda x: (x["grade"], x["learning_area"])):
        lines.append(
            f"| {s['file']} | {s['grade']} | {s['learning_area']} | {s['pages']} | "
            f"{s['chars_per_page']} | {s['chunks']} | {s['status']} |"
        )
    lines.append("")
    lines.append("## What to do next")
    lines.append("")
    lines.append("- **NEEDS_OCR** — the Day 4 finding that KICD PDFs need no OCR held for")
    lines.append("  Science. Any file here is a counter-example worth reporting in Chapter 5.")
    lines.append("- **NO_STRUCTURE** — the design uses a table layout the parser does not")
    lines.append("  recognise. Open one page and compare against a Science design.")
    lines.append("- Re-run the Day 5 retrieval harness against this corpus. Retrieval")
    lines.append("  accuracy measured over 8 chunks is not the same claim as accuracy")
    lines.append("  measured over several hundred.")

    (outdir / "coverage_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{len(all_chunks)} curriculum chunks + {len(all_rubrics)} rubric rows -> {out_json}")
    print(f"Coverage report -> {outdir / 'coverage_report.md'}")
    print("\nStatus summary:")
    for st, n in status_counts.most_common():
        print(f"  {st:<14} {n}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--grades", default="1,2,3,4,5,6")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--outdir", default="data/kicd")
    args = ap.parse_args()

    print(f"build_curriculum_corpus.py {VERSION}\n")

    outdir = Path(args.outdir)
    grades = {int(g) for g in args.grades.split(",") if g.strip()}

    if not any([args.discover, args.download, args.extract, args.all]):
        ap.error("choose --discover, --download, --extract or --all")

    if args.discover or args.all:
        discover(outdir, grades)
    if args.download or args.all:
        download(outdir, args.limit)
    if args.extract or args.all:
        extract(outdir, args.limit)


if __name__ == "__main__":
    main()
