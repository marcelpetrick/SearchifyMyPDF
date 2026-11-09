#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Write a synthetic sample corpus for manual testing and demos.

Usage::

    scripts/generate_samples.py OUT_DIR

Creates nested folders (spaces, umlauts) containing English and German scans, a
born-digital PDF, a mixed digital+scanned PDF, an encrypted, a signed and a corrupt PDF,
plus a naturally named ``Report_searchable.pdf``. All content is synthetic (VISION §11).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import synthetic  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    out = Path(argv[0])
    (out / "Verträge 2025" / "Kunde Ä").mkdir(parents=True, exist_ok=True)
    (out / "Invoices").mkdir(exist_ok=True)
    synthetic.scanned_pdf(out / "Invoices" / "Invoice 0815.pdf")
    synthetic.scanned_pdf(out / "Invoices" / "Invoice 0816.PDF", (synthetic.ENGLISH_LINES,) * 3)
    synthetic.scanned_pdf(
        out / "Verträge 2025" / "Kunde Ä" / "Mietvertrag.pdf", (synthetic.GERMAN_LINES,)
    )
    synthetic.scanned_pdf(out / "Verträge 2025" / "tilted.pdf", rotate=3)
    synthetic.digital_pdf(out / "Born digital.pdf")
    synthetic.mixed_pdf(out / "Mixed digital and scanned.pdf")
    synthetic.encrypted_pdf(out / "Encrypted.pdf")
    synthetic.signed_pdf(out / "Signed.pdf")
    synthetic.corrupt_pdf(out / "Corrupt.pdf")
    synthetic.scanned_pdf(out / "Report_searchable.pdf")
    for path in sorted(out.rglob("*.pdf")):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
