# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Existing-text cross-check with the real Tesseract (#6)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from searchify_pdf.application.workflow import BatchRunner
from searchify_pdf.cli import main as cli
from searchify_pdf.domain.jobs import Outcome, Reason
from searchify_pdf.domain.settings import ExistingTextPolicy, Settings
from searchify_pdf.domain.text_quality import Verdict
from searchify_pdf.engines.ocrmypdf_engine import OcrmypdfEngine
from searchify_pdf.engines.pdf_inspect import inspect_pdf
from searchify_pdf.engines.text_check import TesseractTextChecker
from tests import synthetic
from tests.fakes import NO, ScriptedDecisions

pytestmark = pytest.mark.ocr

CHECK = TesseractTextChecker(("eng", "deu"))


def quality_of(path: Path) -> Verdict:
    return CHECK(path, inspect_pdf(path)).verdict


def test_good_layers_and_born_digital_text_are_good(tmp_path: Path) -> None:
    assert quality_of(synthetic.ocr_layer_pdf(tmp_path / "ocr.pdf")) is Verdict.GOOD
    digital = synthetic.digital_pdf(tmp_path / "d.pdf", [synthetic.REPORT_LINES])
    assert quality_of(digital) is Verdict.GOOD
    assert quality_of(synthetic.mixed_pdf(tmp_path / "m.pdf")) is Verdict.GOOD


def test_garbled_layer_is_poor_and_partly_garbled_is_doubtful(tmp_path: Path) -> None:
    garbled = synthetic.ocr_layer_pdf(tmp_path / "g.pdf", layer_lines=synthetic.GARBLED_LINES)
    result = CHECK(garbled, inspect_pdf(garbled))
    assert result.verdict is Verdict.POOR and result.pages_checked == 1
    partly = synthetic.ocr_layer_pdf(
        tmp_path / "p.pdf",
        layer_lines=(*synthetic.REPORT_LINES[:2], synthetic.GARBLED_LINES[2]),
    )
    assert quality_of(partly) is Verdict.DOUBTFUL


def test_password_protected_source_is_checked_and_left_alone(tmp_path: Path) -> None:
    import pikepdf

    plain = synthetic.ocr_layer_pdf(tmp_path / "plain.pdf", layer_lines=synthetic.GARBLED_LINES)
    locked = tmp_path / "locked.pdf"
    with pikepdf.open(plain) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(user="pw", owner="owner"))
    before = locked.read_bytes()
    assert CHECK(locked, inspect_pdf(locked, "pw")).verdict is Verdict.POOR
    assert locked.read_bytes() == before


def test_without_tesseract_or_on_a_broken_page_the_result_is_unknown(tmp_path: Path) -> None:
    src = synthetic.ocr_layer_pdf(tmp_path / "ocr.pdf")
    info = inspect_pdf(src)
    assert TesseractTextChecker(("eng",), tesseract="no-such-tesseract")(src, info).verdict is (
        Verdict.UNKNOWN
    )
    src.write_bytes(b"%PDF-1.4 truncated")
    assert CHECK(src, info).verdict is Verdict.UNKNOWN


def test_ask_workflow_with_the_real_engine_notes_kept_poor_text(tmp_path: Path) -> None:
    src = synthetic.ocr_layer_pdf(tmp_path / "old.pdf", layer_lines=synthetic.GARBLED_LINES)
    decisions = ScriptedDecisions(text=[NO])
    summary = BatchRunner(
        Settings(existing_text_policy=ExistingTextPolicy.ASK),
        OcrmypdfEngine(),
        decisions=decisions,
        version="t",
    ).run([src])
    assert decisions.qualities[0] is not None
    assert decisions.qualities[0].verdict is Verdict.POOR
    assert summary.results[0].outcome is Outcome.PRESERVED
    assert summary.results[0].notes == (Reason.EXISTING_TEXT_POOR,)


def test_check_text_cli_with_the_real_engine(tmp_path: Path) -> None:
    synthetic.ocr_layer_pdf(tmp_path / "good.pdf")
    synthetic.ocr_layer_pdf(tmp_path / "bad.pdf", layer_lines=synthetic.GARBLED_LINES)
    out = io.StringIO()
    assert cli.main(["--check-text", str(tmp_path)], stdout=out) == cli.EXIT_OK
    lines = {Path(line.split(": ", 1)[0]).name: line for line in out.getvalue().splitlines()}
    assert "looks good" in lines["good.pdf"] and "looks poor" in lines["bad.pdf"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bad.pdf", "good.pdf"]
