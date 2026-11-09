# 0007 — Licensing and component inventory

- Status: accepted
- Date: 2026-11-09

## Decision
- Project license: **GPL-3.0-or-later** (owner's choice). SPDX headers in every source file
  (`scripts/check_headers.py`).
- Bundled stack is GPL-compatible: OCRmyPDF (MPL-2.0), Tesseract/Leptonica/tessdata
  (Apache-2.0 / BSD-2), Qt/PySide6 (LGPL-3.0, dynamically linked shared libraries inside
  the bundle), pikepdf/QPDF (MPL-2.0 / Apache-2.0), pypdfium2/PDFium (Apache-2.0/BSD-3).
- Ghostscript (AGPL) is **not** bundled: output type is ordinary PDF, not PDF/A.
- `scripts/generate_inventory.py` builds `components.json` from the real build
  environment, including the Debian packages of every library Tesseract links against,
  and copies their license texts. Shown offline under About and via `--licenses`.

See `docs/compliance.md` for the release checklist.
