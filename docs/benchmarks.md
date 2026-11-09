# Performance baseline (VISION §7)

Reproduce with `scripts/benchmark.py` (writes `reports/benchmark.json`). Compare future
runs with tolerances (e.g. ±25 % wall time on the same machine), never exact timings.

Baseline 2026-11-10 — Manjaro Linux x86-64, 20 logical CPUs, 31 GiB RAM, Python 3.12.13,
OCRmyPDF 17.14.1 / Tesseract 5.5.3, tessdata_fast 4.1.0 eng+deu, corpus 8 documents × 3
synthetic A4 pages at 200 dpi:

| Mode | Documents at once | Page jobs each | Wall time | Median per document | Peak RSS (process tree) |
| --- | --- | --- | --- | --- | --- |
| Sequential | 1 | 20 | 6.46 s | 0.80 s | 350 MiB |
| Fixed 2 | 2 | 10 | 3.65 s | 0.91 s | 578 MiB |
| Auto | 8 | 2 | 1.53 s | 1.41 s | 1497 MiB |

Observations: documents × page jobs never exceeds the CPU count; Auto's memory estimate
(768 MiB per document) is conservative against the measured ~190 MiB per active document.
