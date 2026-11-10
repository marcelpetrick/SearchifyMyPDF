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

## Executable size (PLAN M2b, steps 25–29)

Measured with `scripts/check_binary_size.py` (PyInstaller's own archive reader). The
pipeline's `size` stage fails above the **95 MB** budget. Every step kept all packaged
E2E tests green (real-life corpus, `docker stop`, terminal prompts, X11 launcher).

| Version | Step | One-file executable | Unpacked at start |
| --- | --- | --- | --- |
| 0.16.14 | baseline | 133.6 MB | 326.0 MB |
| 0.16.22 | runtime dependencies + PyInstaller only (no test/lint tools) | 130.6 MB | 318.7 MB |
| 0.17.0 | Tesseract 5.5.3 from source without libarchive/libxml2/ICU 70/OpenMP | 115.0 MB | 280.4 MB |
| 0.17.1 | strip native libraries; drop AVIF codec, unused lxml/setuptools, embedded Qt platforms and image formats | 102.0 MB | 237.9 MB |
| 0.17.2 | Qt's ICU 73.2 data rebuilt for the en/de UI (32 MB → 3.5 MB) | **90.8 MB (−32 %)** | 209.5 MB (−36 %) |

What remains is the irreducible core: Python (7.7 MB), Python modules (11.4 MB), Qt
(≈ 14 MB), OCRmyPDF's PDF stack (pdfium, qpdf, pdfminer CMaps, lxml, cryptography,
Pillow ≈ 25 MB), Tesseract + Leptonica and language data (≈ 10 MB). PyInstaller already
compresses every entry with zlib level 9; stronger codecs (xz ≈ −28 %) would need a
self-extracting wrapper or AppImage + FUSE, which stock Ubuntu 22.04+ lacks — rejected.

Behaviour unchanged by the trimmed ICU data: German and numeric collation, root collation
for other scripts, case mapping (ß, Turkish İ), time zones and German dates are identical
(compared with the original library). Only Qt's legacy charset decoders (e.g. Shift-JIS)
are gone; Searchify never uses them (file names are UTF-8, text is handled by Python).
