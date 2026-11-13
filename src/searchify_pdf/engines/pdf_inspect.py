# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""PDF inspection and the few PDF edits the application needs, without parsing here.

The application only reads and writes files; every PDF is parsed by the sandboxed PDF
service (:mod:`searchify_pdf.engines.pdf_service`, ADR 0017), so a malicious document
that exploits qpdf or PDFium never runs with the application's rights. Sources are only
ever opened for reading.

Protected PDFs (ADR 0011): a PDF that needs a password to open raises
``password_required`` (no password given) or ``wrong_password``. A PDF that opens
without a password but is encrypted carries owner restrictions. Either way the result
describes the protection so the copy can be encrypted the same way again
(:func:`decrypt_copy`, :func:`encrypt_like`). Passwords are only held in memory; they
reach the service through its pipe, never through arguments or files.
"""

from __future__ import annotations

import dataclasses
import secrets
from pathlib import Path
from typing import Any, Protocol

import pikepdf

from searchify_pdf.domain.jobs import Reason
from searchify_pdf.engines import pdf_ops, pdf_service

MARKER_KEY = pdf_ops.MARKER_KEY


class Backend(Protocol):
    def call(
        self, op: str, args: dict[str, Any], blobs: list[bytes]
    ) -> tuple[dict[str, Any], list[bytes]]: ...


class InProcess:
    """Runs the operations in this process; for tests of the operations only."""

    def call(
        self, op: str, args: dict[str, Any], blobs: list[bytes]
    ) -> tuple[dict[str, Any], list[bytes]]:
        try:
            return pdf_ops.dispatch(op, args, blobs)
        except pdf_ops.OpError as exc:
            raise pdf_service.ServiceError(exc.reason, exc.detail) from exc


def backend() -> Backend:
    return pdf_service.shared()


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


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise PdfInspectionError(Reason.NOT_FOUND, str(exc)) from exc
    except PermissionError as exc:
        raise PdfInspectionError(Reason.UNREADABLE, str(exc)) from exc
    except OSError as exc:
        raise PdfInspectionError(Reason.INVALID_PDF, str(exc)) from exc


def _call(op: str, path: Path, **args: Any) -> tuple[dict[str, Any], list[bytes]]:
    data = _read(path)
    try:
        return backend().call(op, args, [data])
    except pdf_service.ServiceError as exc:
        raise PdfInspectionError(exc.reason, exc.detail) from exc


def _value(op: str, path: Path, **args: Any) -> Any:
    return _call(op, path, **args)[0].get("value")


def _document(op: str, path: Path, **args: Any) -> bytes:
    _, blobs = _call(op, path, **args)
    if len(blobs) != 1:
        raise PdfInspectionError(Reason.VALIDATION_FAILED, f"{op}: no document returned")
    return blobs[0]


def has_marker(path: Path) -> bool:
    """True when the PDF carries the Searchify output marker (cheap metadata check)."""
    try:
        return _value("has_marker", path) is True
    except PdfInspectionError:
        return False


def _protection(raw: Any, password: str) -> Protection | None:
    if raw is None:
        return None
    try:
        permissions = pikepdf.Permissions(**raw["permissions"])
        return Protection(password, bool(raw["owner"]), permissions)
    except (KeyError, TypeError) as exc:
        raise PdfInspectionError(Reason.INVALID_PDF, f"bad protection: {exc}") from exc


def inspect_pdf(path: Path, password: str = "") -> PdfInfo:
    """Inspect ``path``; raise :class:`PdfInspectionError` for unusable inputs.

    ``password`` opens password-protected PDFs; without it they raise
    ``password_required``, with a wrong one ``wrong_password``.
    """
    raw = _value("inspect", path, password=password)
    try:
        flags = tuple(bool(flag) for flag in raw["pages_with_text"])
        page_count = int(raw["page_count"])
        protection = _protection(raw["protection"], password)
        return PdfInfo(
            page_count,
            flags,
            protection,
            signed=bool(raw["signed"]),
            generated_marker=bool(raw["marker"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PdfInspectionError(Reason.INVALID_PDF, f"bad inspection result: {exc}") from exc


def count_pages(path: Path, password: str = "") -> int:
    """Page count used for output validation; raises on an unreadable PDF."""
    pages = _value("count_pages", path, password=password)
    if not isinstance(pages, int) or isinstance(pages, bool):
        raise PdfInspectionError(Reason.VALIDATION_FAILED, f"bad page count {pages!r}")
    return pages


def decrypt_copy(source: Path, password: str, target: Path) -> None:
    """Write an unencrypted copy of ``source`` to ``target`` (a private work file)."""
    target.write_bytes(_document("decrypt", source, password=password))


def encrypt_like(plain: Path, target: Path, protection: Protection) -> None:
    """Encrypt ``plain`` into ``target`` the way the source was protected.

    The copy opens with the same password as the source and keeps its restrictions,
    always with AES-256. The owner password is the source's when the user entered it;
    otherwise it is unknown and a random one is set, so the restrictions cannot be
    lifted from the copy either.
    """
    owner = protection.password if protection.owner else secrets.token_urlsafe(24)
    target.write_bytes(
        _document(
            "encrypt",
            plain,
            user=protection.password,
            owner=owner,
            permissions=protection.permissions._asdict(),
        )
    )


def add_marker(path: Path, version: str) -> None:
    """Stamp our generator marker into the document info of a staging file in place."""
    path.write_bytes(_document("add_marker", path, version=version))


def render_pages(path: Path, password: str, pages: list[int], dpi: int) -> list[tuple[str, bytes]]:
    """Existing text and a grayscale PNG of each of ``pages`` (for the text check)."""
    result, images = _call("render", path, password=password, pages=pages, dpi=dpi)
    texts = result.get("texts")
    if not isinstance(texts, list) or len(texts) != len(pages) or len(images) != len(pages):
        raise PdfInspectionError(Reason.INVALID_PDF, "render: incomplete result")
    return [(str(text), image) for text, image in zip(texts, images, strict=True)]
