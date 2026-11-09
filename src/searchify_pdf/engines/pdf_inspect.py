# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Read-only PDF inspection: page text presence, protection, signatures, our marker.

Sources are only ever opened for reading. pdfium is not thread-safe, so every
pypdfium2 call is serialized through a module-level lock.
"""

from __future__ import annotations

import dataclasses
import threading
from pathlib import Path

import pikepdf
import pypdfium2

from searchify_pdf.domain.jobs import Reason

MARKER_KEY = "/SearchifyPDF"
_PDFIUM_LOCK = threading.Lock()
MIN_TEXT_CHARS = 1


class PdfInspectionError(Exception):
    def __init__(self, reason: Reason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


@dataclasses.dataclass(frozen=True, slots=True)
class PdfInfo:
    page_count: int
    pages_with_text: tuple[bool, ...]
    encrypted: bool = False
    signed: bool = False
    generated_marker: bool = False

    @property
    def text_page_count(self) -> int:
        return sum(self.pages_with_text)

    @property
    def any_text(self) -> bool:
        return any(self.pages_with_text)

    @property
    def all_text(self) -> bool:
        return self.page_count > 0 and all(self.pages_with_text)


def _is_signed(pdf: pikepdf.Pdf) -> bool:
    root = pdf.Root
    if "/Perms" in root:
        return True
    acroform = root.get("/AcroForm")
    if not isinstance(acroform, pikepdf.Dictionary):
        return False
    try:
        sig_flags = int(acroform.get("/SigFlags", 0))
    except (TypeError, ValueError):
        sig_flags = 0
    if sig_flags & 1:
        return True
    fields = acroform.get("/Fields")
    if not isinstance(fields, pikepdf.Array):
        return False
    stack = list(fields)
    seen = 0
    while stack and seen < 10_000:
        seen += 1
        field = stack.pop()
        if not isinstance(field, pikepdf.Dictionary):
            continue
        if field.get("/FT") == pikepdf.Name.Sig and "/V" in field:
            return True
        kids = field.get("/Kids")
        if isinstance(kids, pikepdf.Array):
            stack.extend(kids)
    return False


def has_marker(path: Path) -> bool:
    """True when the PDF carries the Searchify output marker (cheap metadata check)."""
    try:
        with pikepdf.open(path) as pdf:
            return MARKER_KEY in pdf.docinfo
    except (pikepdf.PdfError, OSError, ValueError):
        return False


def page_text_flags(path: Path) -> tuple[bool, ...]:
    with _PDFIUM_LOCK:
        doc = pypdfium2.PdfDocument(str(path))
        try:
            flags = []
            for index in range(len(doc)):
                page = doc[index]
                textpage = page.get_textpage()
                text = textpage.get_text_range()
                flags.append(len(text.strip()) >= MIN_TEXT_CHARS)
                textpage.close()
                page.close()
            return tuple(flags)
        finally:
            doc.close()


def inspect_pdf(path: Path) -> PdfInfo:
    """Inspect ``path``; raise :class:`PdfInspectionError` for unusable inputs."""
    try:
        with pikepdf.open(path) as pdf:
            encrypted = bool(pdf.is_encrypted)
            signed = _is_signed(pdf)
            marker = MARKER_KEY in pdf.docinfo
            page_count = len(pdf.pages)
    except pikepdf.PasswordError as exc:
        raise PdfInspectionError(Reason.ENCRYPTED, str(exc)) from exc
    except PermissionError as exc:
        raise PdfInspectionError(Reason.UNREADABLE, str(exc)) from exc
    except FileNotFoundError as exc:
        raise PdfInspectionError(Reason.NOT_FOUND, str(exc)) from exc
    except (pikepdf.PdfError, OSError, ValueError, RecursionError) as exc:
        raise PdfInspectionError(Reason.INVALID_PDF, str(exc)) from exc
    if encrypted:
        return PdfInfo(page_count, (), encrypted=True, signed=signed, generated_marker=marker)
    try:
        flags = page_text_flags(path)
    except (pypdfium2.PdfiumError, OSError) as exc:
        raise PdfInspectionError(Reason.INVALID_PDF, str(exc)) from exc
    return PdfInfo(page_count, flags, signed=signed, generated_marker=marker)


def count_pages(path: Path) -> int:
    """Page count used for output validation; raises on an unreadable PDF."""
    with pikepdf.open(path) as pdf:
        return len(pdf.pages)


def add_marker(path: Path, version: str) -> None:
    """Stamp our generator marker into the document info of a staging file in place."""
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.docinfo[MARKER_KEY] = pikepdf.String(version)
        pdf.save(path)
