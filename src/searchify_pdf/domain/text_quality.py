# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Quality of an existing text layer, cross-checked against a fresh recognition (#6).

Text presence is not quality (VISION §4.1). The signal used here is *agreement*: the
existing text of a page is compared with what a fresh recognition reads from the
rendered page. Comparison is on case-folded words as a multiset (Dice coefficient), so
a different reading order — e.g. columns — does not count as an error, while garbled,
missing or invented words do. Pages whose rendering shows too few words to judge are
reported as ``unknown`` rather than guessed.
"""

from __future__ import annotations

import collections
import dataclasses
import enum
import re
from collections.abc import Sequence

GOOD_AT = 0.85  # measured: born-digital text and clean OCR layers agree at 0.9 to 1.0
POOR_BELOW = 0.50  # measured: garbled OCR layers agree below 0.3
MIN_WORDS = 5  # fewer recognized words → not enough evidence
MAX_SAMPLES = 3

_WORD = re.compile(r"\w+")


class Verdict(enum.StrEnum):
    GOOD = "good"
    DOUBTFUL = "doubtful"
    POOR = "poor"
    UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True, slots=True)
class TextQuality:
    agreement: float | None  # 0..1, None when there was not enough evidence
    pages_checked: int
    verdict: Verdict

    @property
    def percent(self) -> int:
        return round((self.agreement or 0.0) * 100)


UNKNOWN = TextQuality(None, 0, Verdict.UNKNOWN)


def words(text: str) -> list[str]:
    """Case-folded words with at least one letter (page numbers and dates excluded)."""
    return [w for w in _WORD.findall(text.casefold()) if any(c.isalpha() for c in w)]


def agreement(existing: str, fresh: str) -> float | None:
    """Dice coefficient of the two word multisets; None with too little evidence."""
    a, b = collections.Counter(words(existing)), collections.Counter(words(fresh))
    total_a, total_b = sum(a.values()), sum(b.values())
    if total_b < MIN_WORDS:
        return None
    shared = sum((a & b).values())
    return 2 * shared / (total_a + total_b)


def verdict_for(value: float | None) -> Verdict:
    if value is None:
        return Verdict.UNKNOWN
    if value >= GOOD_AT:
        return Verdict.GOOD
    if value < POOR_BELOW:
        return Verdict.POOR
    return Verdict.DOUBTFUL


def assess(pages: Sequence[tuple[str, str]]) -> TextQuality:
    """Overall quality of ``(existing, fresh)`` page pairs (pooled over all pages)."""
    if not pages:
        return UNKNOWN
    existing = "\n".join(page[0] for page in pages)
    fresh = "\n".join(page[1] for page in pages)
    value = agreement(existing, fresh)
    return TextQuality(value, len(pages), verdict_for(value))


def sample_pages(text_pages: Sequence[int], limit: int = MAX_SAMPLES) -> tuple[int, ...]:
    """Up to ``limit`` page indexes spread over the document: first, middle, last."""
    pages = list(dict.fromkeys(text_pages))
    if len(pages) <= limit:
        return tuple(pages)
    picks = [pages[round(i * (len(pages) - 1) / (limit - 1))] for i in range(limit)]
    return tuple(dict.fromkeys(picks))
