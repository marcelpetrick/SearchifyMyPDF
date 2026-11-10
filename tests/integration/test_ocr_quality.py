# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""OCR quality gate against full ground truth, through the real workflow (PLAN step 31).

Thresholds sit just below the measured values (docs/benchmarks.md "Recognition quality"),
so a regression in the engine, language data, language order or preprocessing fails here.
"""

from pathlib import Path

import pytest

from searchify_pdf.application.workflow import BatchRunner
from searchify_pdf.domain.jobs import Outcome
from searchify_pdf.domain.settings import Settings
from searchify_pdf.engines.ocrmypdf_engine import OcrmypdfEngine
from tests import quality
from tests.textutil import all_text

pytestmark = pytest.mark.ocr

SYNTHETIC_MIN_WORDS = 0.98  # measured: 100 % for every font, resolution and language
SYNTHETIC_MIN_CHARS = 0.99
REAL_MIN_WORDS = 0.92  # measured: 94.2 % (1950 print, ligatures, hyphenation)
REAL_MIN_CHARS = 0.98  # measured: 98.8 %
DEGRADED_MIN_WORDS = 0.90


def convert(src: Path, settings: Settings | None = None) -> str:
    summary = BatchRunner(settings or Settings(), OcrmypdfEngine(), version="q").run([src])
    assert summary.count(Outcome.CONVERTED) == 1, summary
    return all_text(src.with_name(f"{src.stem}_searchable.pdf"))


@pytest.mark.parametrize("dpi", quality.DPIS)
@pytest.mark.parametrize("font", quality.FONTS)
@pytest.mark.parametrize("language", sorted(quality.TEXTS))
def test_synthetic_ground_truth(tmp_path: Path, language: str, font: str, dpi: int) -> None:
    """Default settings (English + German): umlauts and ß included."""
    text = quality.TEXTS[language]
    src = quality.render_pdf(tmp_path / "doc.pdf", text, font=font, dpi=dpi)
    result = quality.score(text, convert(src))
    assert result.words >= SYNTHETIC_MIN_WORDS, result
    assert result.chars >= SYNTHETIC_MIN_CHARS, result


def test_real_1950_print_against_its_published_text_layer(tmp_path: Path) -> None:
    src = tmp_path / "bgbl.pdf"
    src.write_bytes(quality.BGBL_IMAGE_ONLY.read_bytes())
    result = quality.score(quality.bgbl_truth(), convert(src))
    assert result.words >= REAL_MIN_WORDS, result
    assert result.chars >= REAL_MIN_CHARS, result


@pytest.mark.parametrize("variant", quality.DEGRADATIONS)
def test_degraded_german_scan(tmp_path: Path, variant: str) -> None:
    """Scanner defects on the German ground-truth page (deskew on for the skewed one)."""
    text = quality.GERMAN_TEXT
    src = quality.render_pdf(
        tmp_path / "doc.pdf", text, font="DejaVuSerif", dpi=200, variant=variant
    )
    result = quality.score(text, convert(src, Settings(deskew=variant == "skewed")))
    assert result.words >= DEGRADED_MIN_WORDS, result
