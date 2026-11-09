# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Small, typed OCR engine interface so further engines can be added later (VISION §9)."""

from __future__ import annotations

import dataclasses
import enum
import threading
from pathlib import Path
from typing import Protocol

from searchify_pdf.domain.jobs import Reason


class OcrMode(enum.StrEnum):
    PRESERVE_TEXT = "preserve_text"  # keep pages that have text, OCR image-only pages
    REDO_OCR = "redo_ocr"  # replace the old invisible OCR layer, keep visible/vector content


@dataclasses.dataclass(frozen=True, slots=True)
class EngineRequest:
    source: Path
    output: Path
    languages: tuple[str, ...]
    mode: OcrMode
    deskew: bool = False
    rotate_pages: bool = False
    page_jobs: int = 1
    timeout_seconds: float = 1800.0


@dataclasses.dataclass(frozen=True, slots=True)
class EngineResult:
    ok: bool
    reason: Reason = Reason.OK
    detail: str = ""
    notes: tuple[Reason, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class EngineCapabilities:
    name: str
    version: str
    available_languages: tuple[str, ...]
    supports_redo: bool
    redo_supports_deskew: bool


class OcrEngine(Protocol):
    name: str

    def capabilities(self) -> EngineCapabilities: ...

    def readiness_problem(self, languages: tuple[str, ...]) -> tuple[Reason, str] | None:
        """``None`` when the engine can run with ``languages``; otherwise a reason."""
        ...

    def run(self, request: EngineRequest, cancel: threading.Event) -> EngineResult: ...
