# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Real OCR through OCRmyPDF + Tesseract on synthetic and public-domain fixtures (A01, A05)."""

import threading
from pathlib import Path

import pytest

from searchify_pdf.domain.jobs import Reason
from searchify_pdf.engines.base import EngineRequest, OcrMode
from searchify_pdf.engines.ocrmypdf_engine import OcrmypdfEngine
from searchify_pdf.engines.pdf_inspect import count_pages
from tests import synthetic
from tests.textutil import all_text, contains_words, page_texts, sha256

pytestmark = pytest.mark.ocr
REAL = Path(__file__).resolve().parent.parent / "fixtures" / "real" / "ndl583_typewritten_scan.pdf"


def _run(src: Path, out: Path, mode: OcrMode = OcrMode.PRESERVE_TEXT, **kw: object) -> Reason:
    request = EngineRequest(src, out, ("eng", "deu"), mode, **kw)  # type: ignore[arg-type]
    result = OcrmypdfEngine().run(request, threading.Event())
    assert result.ok, result.detail
    return result.reason


def test_scanned_english_becomes_searchable(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(
        tmp_path / "scan.pdf", (synthetic.ENGLISH_LINES, synthetic.GERMAN_LINES)
    )
    before = sha256(src)
    _run(src, tmp_path / "out.pdf")
    texts = page_texts(tmp_path / "out.pdf")
    assert len(texts) == 2
    assert contains_words(texts[0], ["Searchable", "invoice", "Payment", "thirty"])
    assert contains_words(texts[1], ["Rechnung", "Vertrag", "Zahlung"])
    assert sha256(src) == before


def test_mixed_pdf_preserves_digital_and_ocrs_scanned_page(tmp_path: Path) -> None:
    src = synthetic.mixed_pdf(tmp_path / "mixed.pdf")
    _run(src, tmp_path / "out.pdf")
    texts = page_texts(tmp_path / "out.pdf")
    assert contains_words(texts[0], ["Digital", "contract", "preface"])
    assert contains_words(texts[1], ["Searchable", "invoice"])


def test_redo_replaces_previous_ocr_without_rasterizing(tmp_path: Path) -> None:
    src = synthetic.mixed_pdf(tmp_path / "mixed.pdf")
    first = tmp_path / "first.pdf"
    _run(src, first)
    reason = _run(first, tmp_path / "redo.pdf", OcrMode.REDO_OCR, deskew=True)
    assert reason is Reason.OK
    texts = page_texts(tmp_path / "redo.pdf")
    assert contains_words(texts[0], ["Digital", "contract"])  # vector text kept
    assert texts[1].casefold().count("searchable") == 1  # old layer replaced, not duplicated


def test_preprocessing_options(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "rot.pdf", rotate=2)
    _run(src, tmp_path / "out.pdf", deskew=True, rotate_pages=True, page_jobs=2)
    assert contains_words(all_text(tmp_path / "out.pdf"), ["invoice", "Payment"])


def test_corrupt_input_fails_cleanly(tmp_path: Path) -> None:
    src = synthetic.corrupt_pdf(tmp_path / "bad.pdf")
    request = EngineRequest(src, tmp_path / "out.pdf", ("eng",), OcrMode.PRESERVE_TEXT)
    result = OcrmypdfEngine().run(request, threading.Event())
    assert not result.ok
    assert result.reason in {Reason.INVALID_PDF, Reason.ENGINE_FAILED}


def test_real_public_domain_typewritten_scan(tmp_path: Path) -> None:
    before = sha256(REAL)
    _run(REAL, tmp_path / "real.pdf")
    assert count_pages(tmp_path / "real.pdf") == 2
    words = [
        "INTERNATIONAL",
        "PROSECUTION",
        "DOCUMENTARY",
        "Typewritten",
        "Mobilization",
        "Aggressive",
    ]
    assert contains_words(page_texts(tmp_path / "real.pdf")[0], words, minimum=4)
    assert sha256(REAL) == before
