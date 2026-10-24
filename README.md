# AP-World-textbook

Reading notes for Stearns, *AP World History* (8th ed.).

## Files

| File | Purpose |
|---|---|
| `AGENTS.md` | Standing rules for producing chapter notes (structure, source fidelity, detail level, audit). Applied automatically to every chapter request. |
| `Texbook.pdf` | The textbook (998 pages, scanned with an OCR text layer). |
| `chapter-7-class-notes.md` | Formatting exemplar for full reading notes. |
| `chapter-N-quiz-notes.md` | Condensed quiz review notes with a rapid-fire fact table. |
| `tools/pdf_text.py` | Extracts textbook text page-by-page. |

## Reading the textbook

Printed page numbers are **40 lower** than PDF page numbers (printed page 165 = PDF page 205).

```bash
python3 -m venv .venv && .venv/bin/pip install pymupdf   # once
.venv/bin/python tools/pdf_text.py --chapter 7           # whole chapter, with page markers
.venv/bin/python tools/pdf_text.py --pages 165-185       # printed page range
.venv/bin/python tools/pdf_text.py --search "Mansa Musa" # locate a topic
.venv/bin/python tools/pdf_text.py --pages 165 --raw     # untouched OCR layer
```

Output is body text reflowed into paragraphs, with marginal material pulled out and labeled on its own line:

| Label | Contents |
|---|---|
| `[caption]` | figure, map, and table captions plus photo credits |
| `[margin]` | marginal glossary entries |
| `[feature]` | "Visualizing the Past", "Document", "Thinking Historically" boxes |
| `[aside]` | leftover marginal text and stray map labels |

The labels are heuristics: on pages with primary-source boxes or heavy highlighting, a quotation can land in `[margin]`, and full-page map spreads remain label soup. The scan also drops words and garbles some section numbers, so verify headings against the chapter's contents page and never quote corrupted text.

## Asking for notes

Just name the chapter or paste the text: "Make notes for Chapter 8." The rules in `AGENTS.md` cover organization, what to include, source-accuracy limits, and the required output format.
