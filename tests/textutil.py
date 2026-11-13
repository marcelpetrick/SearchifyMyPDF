# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Test helpers for reading back PDF text and checksums."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pypdfium2

from searchify_pdf.engines.pdf_ops import _PDFIUM_LOCK


def page_texts(path: Path, password: str = "") -> list[str]:
    with _PDFIUM_LOCK:
        doc = pypdfium2.PdfDocument(str(path), password=password or None)
        try:
            return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
        finally:
            doc.close()


def all_text(path: Path, password: str = "") -> str:
    return "\n".join(page_texts(path, password))


def contains_words(
    text: str, words: list[str] | tuple[str, ...], *, minimum: int | None = None
) -> bool:
    """True when at least ``minimum`` (default: all) of ``words`` occur, case-insensitively."""
    lowered = text.casefold()
    hits = sum(1 for word in words if word.casefold() in lowered)
    return hits >= (len(words) if minimum is None else minimum)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
