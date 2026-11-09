# 0009 — Recognising generated copies and the explicit override

- Status: accepted
- Date: 2026-11-09

## Decision
- Every published copy carries `/SearchifyPDF <version>` in its document info.
- Folder discovery excludes names ending in the current or any previous suffix (the
  settings keep up to ten former suffixes): with marker → `generated_copy`; without marker
  → `looks_generated` (a naturally named source, reported, not silently dropped).
- **Override:** selecting such a file *explicitly* (picker, drop of the file itself, CLI
  argument) processes it, with a visible note. Files with the marker are never
  re-processed, even when renamed.
- The original of an existing copy is still processed; the output policy decides.

## Consequences
Repeated runs never create `_searchable_searchable.pdf` (tested), suffix changes keep old
copies excluded (tested).
