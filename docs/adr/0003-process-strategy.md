# 0003 — One engine process per document, shared CPU budget

- Status: accepted
- Date: 2026-11-09

## Context
Cancel must stop active work cleanly (VISION §3.4); nested parallelism must not multiply
CPU/memory (§7); a frozen app must not relaunch its GUI by accident (§9).

## Decision
- The workflow runs up to *N* document jobs in a thread pool; each job starts **one
  child process** (`searchify-pdf --searchify-engine-worker <json>` when frozen,
  `python -m searchify_pdf.engines.worker` from source) in its own session.
- Cancel/timeout: `SIGTERM` to the process group, `SIGKILL` after 3 s (psutil tree kill
  on non-POSIX).
- Budget: `documents × page_jobs ≤ cpu_count`; OCRmyPDF page workers are threads and
  Tesseract runs with `OMP_THREAD_LIMIT=1`.
- Auto = min(cpu/2, available memory / 768 MiB, 8, number of documents).
- The worker flag is handled before any UI import.

## Consequences
Crashes in OCR cannot take down the UI; no orphaned Tesseract processes (tested).
