# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Read-only PDF inspection: page text presence, protection, signatures, our marker.

Sources are only ever opened for reading. pdfium is not thread-safe, so every
pypdfium2 call is serialized through a module-level lock.

Protected PDFs (ADR 0011): a PDF that needs a password to open raises
``password_required`` (no password given) or ``wrong_password``. A PDF that opens
without a password but is encrypted carries owner restrictions. Either way the result
describes the protection so the copy can be encrypted the same way again
(:func:`decrypt_copy`, :func:`encrypt_like`). Passwords are only held in memory.
"""

from __future__ import annotations

import contextlib
import dataclasses
import secrets
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pikepdf
import pypdfium2

from searchify_pdf.domain.jobs import Reason

MARKER_KEY = "/SearchifyPDF"
_PDFIUM_LOCK = threading.Lock()
# qpdf's encryption code is not thread-safe in every build: on Windows, opening a
# protected PDF while another worker thread encrypts or decrypts one fails with
# "invalid password". These operations take milliseconds next to OCR, so all pikepdf
# access in this process is serialized (OCR itself runs in a separate worker process).
_PIKEPDF_LOCK = threading.Lock()
MIN_TEXT_CHARS = 1


class PdfInspectionError(Exception):
    def __init__(self, reason: Reason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


@dataclasses.dataclass(frozen=True, slots=True)
class Protection:
    """How a source PDF is encrypted; enough to protect its copy the same way.

    ``password`` is the one that opened it (``""`` for owner-restricted PDFs that open
    without one). ``owner`` is True when that password is the owner password, i.e. it
    grants full rights. ``permissions`` are the restrictions recorded in the source.
    """

    password: str
    owner: bool
    permissions: pikepdf.Permissions = dataclasses.field(repr=False)

    @property
    def restricted_only(self) -> bool:
        """Opens without a password but restricts what readers may do (owner password)."""
        return self.password == "" and not self.owner

    def __repr__(self) -> str:  # never show the password in logs or test output
        return f"Protection(password={'***' if self.password else ''!r}, owner={self.owner})"


@dataclasses.dataclass(frozen=True, slots=True)
class PdfInfo:
    page_count: int
    pages_with_text: tuple[bool, ...]
    protection: Protection | None = None
    signed: bool = False
    generated_marker: bool = False

    @property
    def encrypted(self) -> bool:
        return self.protection is not None

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


def _password_error(password: str, exc: Exception) -> PdfInspectionError:
    reason = Reason.WRONG_PASSWORD if password else Reason.PASSWORD_REQUIRED
    return PdfInspectionError(reason, str(exc))


@contextlib.contextmanager
def _open_pdf(path: Path, **kwargs: Any) -> Iterator[pikepdf.Pdf]:
    with _PIKEPDF_LOCK, pikepdf.open(path, **kwargs) as pdf:
        yield pdf


def has_marker(path: Path) -> bool:
    """True when the PDF carries the Searchify output marker (cheap metadata check)."""
    try:
        with _open_pdf(path) as pdf:
            return MARKER_KEY in pdf.docinfo
    except (pikepdf.PdfError, OSError, ValueError):
        return False


def page_text_flags(path: Path, password: str = "") -> tuple[bool, ...]:
    with _PDFIUM_LOCK:
        doc = pypdfium2.PdfDocument(str(path), password=password or None)
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


def inspect_pdf(path: Path, password: str = "") -> PdfInfo:
    """Inspect ``path``; raise :class:`PdfInspectionError` for unusable inputs.

    ``password`` opens password-protected PDFs; without it they raise
    ``password_required``, with a wrong one ``wrong_password``.
    """
    try:
        with _open_pdf(path, password=password) as pdf:
            protection = None
            if pdf.is_encrypted:
                protection = Protection(password, bool(pdf.owner_password_matched), pdf.allow)
            signed = _is_signed(pdf)
            marker = MARKER_KEY in pdf.docinfo
            page_count = len(pdf.pages)
    except pikepdf.PasswordError as exc:
        raise _password_error(password, exc) from exc
    except PermissionError as exc:
        raise PdfInspectionError(Reason.UNREADABLE, str(exc)) from exc
    except FileNotFoundError as exc:
        raise PdfInspectionError(Reason.NOT_FOUND, str(exc)) from exc
    except (pikepdf.PdfError, OSError, ValueError, RecursionError) as exc:
        raise PdfInspectionError(Reason.INVALID_PDF, str(exc)) from exc
    try:
        flags = page_text_flags(path, password)
    except (pypdfium2.PdfiumError, OSError) as exc:
        raise PdfInspectionError(Reason.INVALID_PDF, str(exc)) from exc
    return PdfInfo(page_count, flags, protection, signed=signed, generated_marker=marker)


def count_pages(path: Path, password: str = "") -> int:
    """Page count used for output validation; raises on an unreadable PDF."""
    with _open_pdf(path, password=password) as pdf:
        return len(pdf.pages)


def decrypt_copy(source: Path, password: str, target: Path) -> None:
    """Write an unencrypted copy of ``source`` to ``target`` (a private work file)."""
    with _open_pdf(source, password=password) as pdf:
        pdf.save(target)


def encrypt_like(plain: Path, target: Path, protection: Protection) -> None:
    """Encrypt ``plain`` into ``target`` the way the source was protected.

    The copy opens with the same password as the source and keeps its restrictions,
    always with AES-256. The owner password is the source's when the user entered it;
    otherwise it is unknown and a random one is set, so the restrictions cannot be
    lifted from the copy either.
    """
    owner = protection.password if protection.owner else secrets.token_urlsafe(24)
    encryption = pikepdf.Encryption(
        owner=owner, user=protection.password, R=6, allow=protection.permissions
    )
    with _open_pdf(plain) as pdf:
        pdf.save(target, encryption=encryption)


def add_marker(path: Path, version: str) -> None:
    """Stamp our generator marker into the document info of a staging file in place."""
    with _open_pdf(path, allow_overwriting_input=True) as pdf:
        pdf.docinfo[MARKER_KEY] = pikepdf.String(version)
        pdf.save(path)
