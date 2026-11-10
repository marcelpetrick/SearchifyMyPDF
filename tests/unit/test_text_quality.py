# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Existing-text quality signal (#6): agreement with a fresh recognition."""

from __future__ import annotations

import pytest

from searchify_pdf.domain.settings import UiLanguage
from searchify_pdf.domain.text_quality import (
    GOOD_AT,
    MIN_WORDS,
    POOR_BELOW,
    UNKNOWN,
    TextQuality,
    Verdict,
    agreement,
    assess,
    sample_pages,
    verdict_for,
    words,
)
from searchify_pdf.i18n import quality_text

TEXT = "The quarterly report was approved; revenue increased in March"


def test_words_are_case_folded_and_need_a_letter() -> None:
    assert words("Für 2025-03-14 the Report, Seite 3a!") == ["für", "the", "report", "seite", "3a"]


def test_identical_text_agrees_fully_and_order_does_not_matter() -> None:
    assert agreement(TEXT, TEXT) == 1.0
    assert agreement(" ".join(reversed(TEXT.split())), TEXT) == 1.0


def test_garbled_and_partial_text() -> None:
    assert agreement("Tbe qnarterly rcport", TEXT) == 0.0
    half = " ".join(TEXT.split()[:5])  # 5 of the 9 words, all correct
    assert agreement(half, TEXT) == pytest.approx(2 * 5 / (5 + 9))
    assert agreement("", TEXT) == 0.0


def test_repeated_words_count_as_often_as_they_occur() -> None:
    fresh = "alpha beta gamma delta epsilon"
    assert agreement("alpha alpha alpha alpha alpha", fresh) == pytest.approx(2 / 10)


def test_too_little_fresh_text_is_no_evidence() -> None:
    few = " ".join(["word"] * (MIN_WORDS - 1))
    assert agreement(TEXT, few) is None
    assert agreement(few, " ".join(["word"] * MIN_WORDS)) is not None


@pytest.mark.parametrize(
    ("value", "verdict"),
    [
        (None, Verdict.UNKNOWN),
        (1.0, Verdict.GOOD),
        (GOOD_AT, Verdict.GOOD),
        (GOOD_AT - 0.001, Verdict.DOUBTFUL),
        (POOR_BELOW, Verdict.DOUBTFUL),
        (POOR_BELOW - 0.001, Verdict.POOR),
        (0.0, Verdict.POOR),
    ],
)
def test_verdict_thresholds(value: float | None, verdict: Verdict) -> None:
    assert verdict_for(value) is verdict


def test_assess_pools_the_sampled_pages() -> None:
    assert assess([]) == UNKNOWN
    good = assess([(TEXT, TEXT), (TEXT, TEXT)])
    assert good == TextQuality(1.0, 2, Verdict.GOOD) and good.percent == 100
    mixed = assess([(TEXT, TEXT), ("x", TEXT)])
    assert mixed.pages_checked == 2 and mixed.verdict is Verdict.DOUBTFUL
    assert assess([("a", "b")]) == TextQuality(None, 1, Verdict.UNKNOWN)
    assert UNKNOWN.percent == 0


def test_sample_pages_spread_over_the_document() -> None:
    assert sample_pages([]) == ()
    assert sample_pages([4]) == (4,)
    assert sample_pages([0, 2, 5]) == (0, 2, 5)
    assert sample_pages([3, 3, 7]) == (3, 7)
    assert sample_pages(list(range(10))) == (0, 4, 9)
    assert sample_pages(list(range(100)), limit=2) == (0, 99)


def test_quality_sentences_in_both_languages() -> None:
    poor = TextQuality(0.31, 3, Verdict.POOR)
    assert quality_text(poor) == (
        "A fresh recognition of 3 page(s) agrees with the existing text on only 31 % of the "
        "words: it looks poor, replacing it is recommended."
    )
    assert "31 %" in quality_text(poor, UiLanguage.GERMAN)
    assert "looks good" in quality_text(TextQuality(0.97, 1, Verdict.GOOD))
    assert "doubtful" in quality_text(TextQuality(0.7, 1, Verdict.DOUBTFUL))
    assert "could not be checked" in quality_text(UNKNOWN)
