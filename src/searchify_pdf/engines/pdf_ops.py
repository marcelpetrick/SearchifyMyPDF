# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""The PDF parsing operations behind :mod:`searchify_pdf.engines.pdf_inspect` (#13).

Everything here parses untrusted documents with native code (qpdf through pikepdf,
PDFium through pypdfium2). It runs inside the sandboxed PDF service process
(:mod:`searchify_pdf.engines.pdf_service`), never in the application itself, and it
never touches the file system: documents come in as bytes and results go out as plain
JSON values and bytes. :func:`dispatch` is the single entry point.

pdfium is not thread-safe and qpdf's encryption code is not thread-safe in every build
(Windows: "invalid password" while another thread encrypts), so every call is
serialized; the service handles one request at a time anyway.
"""

from __future__ import annotations

import contextlib
import io
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pikepdf
import pypdfium2

from searchify_pdf.domain.jobs import Reason

MARKER_KEY = "/SearchifyPDF"
MIN_TEXT_CHARS = 1
MAX_SIGNATURE_FIELDS = 10_000
_PDFIUM_LOCK = threading.Lock()
_PIKEPDF_LOCK = threading.Lock()

Result = tuple[dict[str, Any], list[bytes]]


class OpError(Exception):
    """A document problem with a stable reason code (the detail is diagnostic only)."""

    def __init__(self, reason: Reason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


@contextlib.contextmanager
def _open_pdf(data: bytes, password: str = "") -> Iterator[pikepdf.Pdf]:
    with _PIKEPDF_LOCK, pikepdf.open(io.BytesIO(data), password=password) as pdf:
        yield pdf


def _save(pdf: pikepdf.Pdf, **kwargs: Any) -> bytes:
    out = io.BytesIO()
    pdf.save(out, **kwargs)
    return out.getvalue()


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
    while stack and seen < MAX_SIGNATURE_FIELDS:
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


def page_text_flags(data: bytes, password: str = "") -> list[bool]:
    with _PDFIUM_LOCK:
        doc = pypdfium2.PdfDocument(data, password=password or None)
        try:
            flags = []
            for index in range(len(doc)):
                page = doc[index]
                textpage = page.get_textpage()
                text = textpage.get_text_range()
                flags.append(len(text.strip()) >= MIN_TEXT_CHARS)
                textpage.close()
                page.close()
            return flags
        finally:
            doc.close()


def has_marker(data: bytes) -> bool:
    try:
        with _open_pdf(data) as pdf:
            return MARKER_KEY in pdf.docinfo
    except (pikepdf.PdfError, ValueError, RecursionError):
        return False


def inspect(data: bytes, password: str) -> dict[str, Any]:
    try:
        with _open_pdf(data, password) as pdf:
            protection = None
            if pdf.is_encrypted:
                protection = {
                    "owner": bool(pdf.owner_password_matched),
                    "permissions": pdf.allow._asdict(),
                }
            signed = _is_signed(pdf)
            marker = MARKER_KEY in pdf.docinfo
            page_count = len(pdf.pages)
    except pikepdf.PasswordError as exc:
        reason = Reason.WRONG_PASSWORD if password else Reason.PASSWORD_REQUIRED
        raise OpError(reason, str(exc)) from exc
    except (pikepdf.PdfError, ValueError, RecursionError) as exc:
        raise OpError(Reason.INVALID_PDF, str(exc)) from exc
    try:
        flags = page_text_flags(data, password)
    except pypdfium2.PdfiumError as exc:
        raise OpError(Reason.INVALID_PDF, str(exc)) from exc
    return {
        "page_count": page_count,
        "pages_with_text": flags,
        "protection": protection,
        "signed": signed,
        "marker": marker,
    }


def count_pages(data: bytes, password: str) -> int:
    with _open_pdf(data, password) as pdf:
        return len(pdf.pages)


def decrypt(data: bytes, password: str) -> bytes:
    with _open_pdf(data, password) as pdf:
        return _save(pdf)


def encrypt(data: bytes, user: str, owner: str, permissions: dict[str, bool]) -> bytes:
    allow = pikepdf.Permissions(**permissions)
    encryption = pikepdf.Encryption(owner=owner, user=user, R=6, allow=allow)
    with _open_pdf(data) as pdf:
        return _save(pdf, encryption=encryption)


def add_marker(data: bytes, version: str) -> bytes:
    with _open_pdf(data) as pdf:
        pdf.docinfo[MARKER_KEY] = pikepdf.String(version)
        return _save(pdf)


def render(data: bytes, password: str, pages: list[int], dpi: int) -> Result:
    """Existing text of ``pages`` and a grayscale PNG of each (for the text check)."""
    texts, images = [], []
    with _PDFIUM_LOCK:
        doc = pypdfium2.PdfDocument(data, password=password or None)
        try:
            for index in pages:
                page = doc[index]
                textpage = page.get_textpage()
                texts.append(textpage.get_text_range())
                textpage.close()
                bitmap = page.render(scale=dpi / 72, grayscale=True)
                png = io.BytesIO()
                bitmap.to_pil().save(png, format="PNG")
                images.append(png.getvalue())
                bitmap.close()
                page.close()
        finally:
            doc.close()
    return {"texts": texts}, images


def _one(value: Any) -> Result:
    return {"value": value}, []


def _bytes(value: bytes) -> Result:
    return {}, [value]


OPERATIONS: dict[str, Callable[[dict[str, Any], list[bytes]], Result]] = {
    "has_marker": lambda a, b: _one(has_marker(b[0])),
    "inspect": lambda a, b: _one(inspect(b[0], a["password"])),
    "count_pages": lambda a, b: _one(count_pages(b[0], a["password"])),
    "decrypt": lambda a, b: _bytes(decrypt(b[0], a["password"])),
    "encrypt": lambda a, b: _bytes(encrypt(b[0], a["user"], a["owner"], a["permissions"])),
    "add_marker": lambda a, b: _bytes(add_marker(b[0], a["version"])),
    "render": lambda a, b: render(b[0], a["password"], list(a["pages"]), int(a["dpi"])),
}


def dispatch(op: str, args: dict[str, Any], blobs: list[bytes]) -> Result:
    """Run one operation; any failure becomes :class:`OpError` with a reason code."""
    operation = OPERATIONS.get(op)
    if operation is None:
        raise OpError(Reason.ENGINE_FAILED, f"unknown operation {op!r}")
    try:
        return operation(args, blobs)
    except OpError:
        raise
    except pikepdf.PasswordError as exc:
        raise OpError(Reason.WRONG_PASSWORD, str(exc)) from exc
    except (KeyError, IndexError, TypeError) as exc:
        raise OpError(Reason.ENGINE_FAILED, f"bad request: {exc}") from exc
    except Exception as exc:  # parser failures of any kind: the document is unusable
        raise OpError(Reason.INVALID_PDF, f"{type(exc).__name__}: {exc}") from exc
