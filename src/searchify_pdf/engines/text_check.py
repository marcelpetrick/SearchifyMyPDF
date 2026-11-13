# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Cross-check an existing text layer against a fresh Tesseract recognition (#6).

Up to three pages that already carry text are rendered (the invisible OCR layer is not
drawn, visible text is), recognized with the configured languages, and compared with
the page's existing text (:mod:`searchify_pdf.domain.text_quality`). The source is
only read, and rendered by the sandboxed PDF service; renderings live in a private
temporary folder that is always removed.
Any failure (no Tesseract, timeout, damaged page) yields ``unknown``, never a guess.

The sampled pages are recognized in parallel, each Tesseract single-threaded: an
OpenMP-enabled Tesseract would otherwise oversubscribe the CPU (measured 2.6x slower on
a dense 1950 page, 10.0 s → 3.8 s).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from searchify_pdf.domain.text_quality import UNKNOWN, TextQuality, assess, sample_pages
from searchify_pdf.engines.ocrmypdf_engine import recognition_order
from searchify_pdf.engines.pdf_inspect import PdfInfo, PdfInspectionError, render_pages

RENDER_DPI = 200


def _extract(source: Path, password: str, pages: Sequence[int], folder: Path) -> list[str]:
    """Existing text of ``pages``; each page is also rendered to ``folder/<index>.png``."""
    texts = []
    rendered = render_pages(source, password, list(pages), RENDER_DPI)
    for index, (text, png) in zip(pages, rendered, strict=True):
        (folder / f"{index}.png").write_bytes(png)
        texts.append(text)
    return texts


class TesseractTextChecker:
    """``checker(source, info)`` → :class:`TextQuality` of the existing text layer."""

    def __init__(
        self,
        languages: Sequence[str],
        *,
        tesseract: str = "tesseract",
        timeout_seconds: float = 120.0,
    ) -> None:
        self.languages = "+".join(recognition_order(languages))
        self.tesseract = tesseract
        self.timeout_seconds = timeout_seconds

    def _recognize(self, exe: str, image: Path) -> str:
        done = subprocess.run(
            [exe, str(image), "stdout", "-l", self.languages],
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=True,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
        return done.stdout

    def __call__(self, source: Path, info: PdfInfo) -> TextQuality:
        pages = sample_pages([i for i, has in enumerate(info.pages_with_text) if has])
        exe = shutil.which(self.tesseract)
        if not pages or exe is None:
            return UNKNOWN
        password = info.protection.password if info.protection else ""
        folder = Path(tempfile.mkdtemp(prefix="searchify-check-"))
        try:
            existing = _extract(source, password, pages, folder)
            images = [folder / f"{index}.png" for index in pages]
            with ThreadPoolExecutor(len(images), thread_name_prefix="text-check") as pool:
                fresh = list(pool.map(lambda image: self._recognize(exe, image), images))
        except (OSError, ValueError, subprocess.SubprocessError, PdfInspectionError):
            return UNKNOWN
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        return assess(list(zip(existing, fresh, strict=True)))
