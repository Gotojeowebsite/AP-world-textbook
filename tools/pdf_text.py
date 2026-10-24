#!/usr/bin/env python3
"""Extract text from Texbook.pdf so chapter notes can be written from the real source.

The PDF is a scan with an OCR text layer. That layer splices margin glossaries,
captions, sidebars, and photo credits into the middle of body paragraphs, so this
script keeps the page's own reading order but pulls aside, and labels:

    [caption]  figure/map/table captions and photo credits
    [margin]   marginal glossary entries
    [feature]  "Visualizing the Past" / "Document" / "Thinking Historically" boxes
    [aside]    leftover marginal text and stray map labels

Everything else is emitted as body text, reflowed into paragraphs. Pass --raw to
see the untouched text layer for comparison.

Printed page numbers run 40 behind PDF page numbers (printed 127 = PDF page 167);
the offset is detected from the running headers, not hardcoded.

Examples
--------
    .venv/bin/python tools/pdf_text.py --chapter 7            # whole chapter
    .venv/bin/python tools/pdf_text.py --pages 165-185        # printed page range
    .venv/bin/python tools/pdf_text.py --search "Mansa Musa"  # find pages
    .venv/bin/python tools/pdf_text.py --pages 168 --raw      # unprocessed layer
    .venv/bin/python tools/pdf_text.py --pages 168 --out /tmp/p168.txt
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:  # pragma: no cover - dependency guidance
    sys.exit("Missing PyMuPDF. Run: python3 -m venv .venv && .venv/bin/pip install pymupdf")

PDF = Path(__file__).resolve().parent.parent / "Texbook.pdf"

# Running header, e.g. "Chapter 7: African Civilizations and the Spread of Islam\n169"
HEADER = re.compile(r"^Chapter\s+(\d+):[^\n]*\n\s*(\d{1,3})\s*$", re.MULTILINE)
CAPTION_START = re.compile(r"^(figure|map|table|chart)\s*\d", re.IGNORECASE)
FEATURE_START = re.compile(r"^(visualizing the past|thinking historically|document|box)\b", re.IGNORECASE)
CREDIT = re.compile(r"alamy|getty|photobank|art resource|library of congress|reuters|ap images", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def squash(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def spans_text(spans: list[dict]) -> str:
    text = squash(" ".join(s["text"].strip() for s in spans if s["text"].strip()))
    return text.lstrip("_ ")


def span_center(span: dict) -> float:
    return (span["bbox"][0] + span["bbox"][2]) / 2


def line_height(spans: list[dict]) -> float:
    return statistics.median(s["bbox"][3] - s["bbox"][1] for s in spans) or 8.0


def dehyphenate(left: str, right: str) -> str:
    if left.endswith("-") and right[:1].islower():
        return left[:-1] + right
    if left.endswith(("-", "—")):
        return left + right
    return left + " " + right


# --------------------------------------------------------------------------- #
# Page extraction
# --------------------------------------------------------------------------- #
class Record:
    """One visual line of text, with of the spans kept as body text."""

    __slots__ = ("spans", "height", "kind", "x0", "y0", "x1", "y1")

    def __init__(self, spans: list[dict], kind: str) -> None:
        self.spans = spans
        self.kind = kind
        boxes = [s["bbox"] for s in spans]
        self.x0 = min(b[0] for b in boxes)
        self.y0 = min(b[1] for b in boxes)
        self.x1 = max(b[2] for b in boxes)
        self.y1 = max(b[3] for b in boxes)
        self.height = line_height(spans)

    @property
    def text(self) -> str:
        return spans_text(self.spans)


def page_records(page: "pymupdf.Page") -> list[Record]:
    """Flatten the page's text layer into visual lines, in document order."""
    records: list[Record] = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if spans:
                records.append(Record(spans, "body"))
    return records


def body_edge(records: list[Record], width: float) -> float:
    """Left edge of the main text column, measured from full-width lines."""
    wide = [r.x0 for r in records if (r.x1 - r.x0) >= 0.5 * width]
    if not wide:
        wide = [r.x0 for r in records if (r.x1 - r.x0) >= 0.32 * width]
    if not wide:
        return 0.0
    return statistics.median(wide)


def page_text(page: "pymupdf.Page") -> str:
    width, height = page.rect.width, page.rect.height
    records = page_records(page)
    if not records:
        return ""

    edge = body_edge(records, width) - 4.0
    body: list[Record] = []
    margin: list[Record] = []
    captions: list[Record] = []
    features: list[Record] = []
    asides: list[Record] = []

    mode: str | None = None
    anchor: Record | None = None
    group = (0.0, 0.0, 0.0, 0.0)  # x0, y0, x1, y1 of the open caption/feature box
    for record in records:
        if in_page_margin(record, height):
            continue

        # Continue an open caption/feature box while lines stay inside it.
        if mode and anchor is not None:
            pad = max(12.0, 0.08 * width)
            aligned = abs(record.x0 - group[0]) <= 0.06 * width
            contained = record.x0 >= group[0] - pad and record.x1 <= group[2] + pad
            inside = (
                (aligned or contained)
                and record.y0 - anchor.y1 < 2.6 * record.height
            )
            if inside:
                (captions if mode == "caption" else features).append(record)
                anchor = record
                group = (min(group[0], record.x0), group[1], max(group[2], record.x1), record.y1)
                continue
            mode = None

        text = record.text.lstrip("_ ")
        if CAPTION_START.match(text):
            mode, anchor = "caption", record
            group = (record.x0, record.y0, record.x1, record.y1)
            captions.append(record)
            continue
        if FEATURE_START.match(text):
            mode, anchor = "feature", record
            group = (record.x0, record.y0, record.x1, record.y1)
            features.append(record)
            continue

        # Blocks that sit wholly left of the text column are marginal.
        if edge > 0 and record.x1 <= edge:
            (margin if (record.x1 - record.x0) < 0.3 * width else asides).append(record)
            continue
        if edge > 0 and record.x0 < edge - 0.18 * width:
            asides.append(record)
            continue

        # Split a line that begins in the margin but runs into the text column.
        if edge > 0:
            kept, moved = [], []
            for span in record.spans:
                (moved if span_center(span) < edge else kept).append(span)
            if moved and not kept:
                margin.append(Record(moved, "margin"))
                continue
            if moved:
                margin.append(Record(moved, "margin"))
                record = Record(kept, "body")

        if CREDIT.search(record.text) and record.height < 0.9 * statistics.median(
            r.height for r in records
        ):
            asides.append(record)
            continue
        body.append(record)

    return render(body, margin, captions, features, asides, width)


def in_page_margin(record: Record, height: float) -> bool:
    """Running heads, folios, and page numbers above or below the text block."""
    return record.y1 < 0.05 * height or record.y0 > 0.95 * height


def render(body: list[Record], margin: list[Record], captions: list[Record],
           features: list[Record], asides: list[Record], width: float) -> str:
    parts = [part for part in (render_body(body, width),) if part]
    for label, group in (("caption", captions), ("margin", margin),
                         ("feature", features), ("aside", asides)):
        if group:
            parts.append(f"[{label}] " + join(group))
    return "\n\n".join(parts)


def join(lines: list[Record]) -> str:
    text = ""
    for record in lines:
        text = record.text if not text else dehyphenate(text, record.text)
    return text


def columns(records: list[Record], width: float) -> list[list[Record]]:
    """Group body lines into side-by-side columns.

    Lines are first clustered by horizontal overlap (tolerating the jittery boxes
    of this scan), then any cluster with two distinct left edges is split apart so
    two-column pages are read one column at a time instead of row by row.
    """
    bands: list[list[Record]] = []
    for record in sorted(records, key=lambda l: (l.y0, l.x0)):
        for band in bands:
            x0 = min(r.x0 for r in band)
            x1 = max(r.x1 for r in band)
            overlap = min(record.x1, x1) - max(record.x0, x0)
            narrow = min(record.x1 - record.x0, x1 - x0) or 1.0
            if overlap > 0.5 * narrow:
                band.append(record)
                break
        else:
            bands.append([record])

    split: list[list[Record]] = []
    for band in bands:
        band.sort(key=lambda r: r.x0)
        current = [band[0]]
        for record in band[1:]:
            if record.x0 - current[-1].x0 > 0.22 * width:
                split.append(current)
                current = [record]
            else:
                current.append(record)
        split.append(current)

    # Short lines can land in the wrong column; rejoin bands that share an x-range.
    merged = True
    while merged and len(split) > 1:
        merged = False
        for i, band in enumerate(split):
            for j in range(i + 1, len(split)):
                other = split[j]
                a0, a1 = min(r.x0 for r in band), max(r.x1 for r in band)
                b0, b1 = min(r.x0 for r in other), max(r.x1 for r in other)
                same_edge = abs(a0 - b0) <= 0.12 * width
                overlaps = min(a1, b1) - max(a0, b0) > 0.55 * (min(a1 - a0, b1 - b0) or 1.0)
                if same_edge and overlaps:
                    band.extend(other)
                    split.pop(j)
                    merged = True
                    break
            if merged:
                break
    return sorted(split, key=lambda b: min(r.x0 for r in b))


def render_body(lines: list[Record], width: float) -> str:
    """Read each column top-to-bottom, then reflow it into paragraphs."""
    if not lines:
        return ""
    height = statistics.median(l.height for l in lines) or 8.0
    paragraphs: list[str] = []
    for band in columns(lines, width):
        band.sort(key=lambda l: (round(l.y0 / 2.0), l.x0))
        current = [band[0]]
        for prev, line in zip(band, band[1:]):
            if line.y0 - prev.y1 < 1.6 * height:
                current.append(line)
            else:
                paragraphs.append(join(current))
                current = [line]
        paragraphs.append(join(current))
    return "\n\n".join(p for p in paragraphs if p)


# --------------------------------------------------------------------------- #
# Document scanning
# --------------------------------------------------------------------------- #
def scan_headers(doc: "pymupdf.Document") -> tuple[int, dict[int, list[int]]]:
    """Map chapter number -> PDF page indices carrying that chapter's running header."""
    found: dict[int, list[int]] = {}
    deltas: list[int] = []
    for i in range(doc.page_count):
        m = HEADER.search(doc.load_page(i).get_text("text"))
        if not m:
            continue
        chapter, printed = int(m.group(1)), int(m.group(2))
        found.setdefault(chapter, []).append(i)
        deltas.append((i + 1) - printed)
    return (int(statistics.median(deltas)) if deltas else 0), found


def max_font_size(page: "pymupdf.Page") -> float:
    return max(
        (
            span["size"]
            for block in page.get_text("dict")["blocks"]
            if block["type"] == 0
            for line in block["lines"]
            for span in line["spans"]
        ),
        default=0.0,
    )


def find_opener(doc: "pymupdf.Document", first_header: int, window: int = 8) -> int:
    """The chapter title page before the first running header (body text is ~10pt)."""
    for i in range(first_header, max(first_header - window, -1), -1):
        if max_font_size(doc.load_page(i)) >= 22:
            return i
    return max(first_header - 2, 0)


def chapter_range(doc: "pymupdf.Document", pages: dict[int, list[int]], chapter: int) -> tuple[int, int]:
    """PDF page indices (0-based) covering a chapter, including its title page."""
    if chapter not in pages:
        raise SystemExit(f"Could not locate chapter {chapter} in {PDF.name}")
    first = find_opener(doc, min(pages[chapter]))
    last = max(pages[chapter]) + 2
    following = [c for c in pages if c > chapter]
    if following:
        last = min(last, find_opener(doc, min(pages[min(following)])) - 1)
    return first, min(last, doc.page_count - 1)


def dump(doc: "pymupdf.Document", first: int, last: int, offset: int, raw: bool) -> str:
    chunks = []
    for i in range(first, last + 1):
        page = doc.load_page(i)
        text = page.get_text("text").strip() if raw else page_text(page)
        chunks.append(f"=== PDF p{i + 1} | book p{i + 1 - offset} ===\n{text}".rstrip())
    return "\n\n".join(chunks) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chapter", type=int, help="chapter number to dump")
    ap.add_argument("--pages", help="printed page range, e.g. 165-185")
    ap.add_argument("--search", help="literal text to locate (prints PDF + book page numbers)")
    ap.add_argument("--raw", action="store_true", help="dump the untouched OCR text layer")
    ap.add_argument("--out", help="write output to this file instead of stdout")
    args = ap.parse_args()

    doc = pymupdf.open(PDF)
    offset, pages = scan_headers(doc)

    if args.search:
        needle = args.search.lower()
        hits = [
            f"PDF p{i + 1} | book p{i + 1 - offset}"
            for i in range(doc.page_count)
            if needle in doc.load_page(i).get_text("text").lower()
        ]
        print(f"{len(hits)} page(s) contain {args.search!r} (page offset {offset}):")
        print("\n".join(hits[:80]))
        return

    if args.chapter is not None:
        first, last = chapter_range(doc, pages, args.chapter)
    elif args.pages:
        lo, _, hi = args.pages.partition("-")
        first = int(lo) - 1 + offset
        last = int(hi or lo) - 1 + offset
    else:
        ap.error("pass --chapter, --pages, or --search")

    out = dump(doc, max(first, 0), min(last, doc.page_count - 1), offset, args.raw)
    if args.out:
        Path(args.out).write_text(out)
        print(f"wrote {len(out):,} chars to {args.out}")
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
