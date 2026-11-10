# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""OCR quality measurement against known ground truth (PLAN step 31).

Synthetic documents are rendered from :data:`ENGLISH_TEXT` / :data:`GERMAN_TEXT` with real
TrueType fonts (``fixtures/fonts``: DejaVu Sans/Serif, which have ä, ö, ü, ß). The real
1950 Bundesgesetzblatt page is measured against the publisher's own text layer.

Metrics on case-folded word sequences (``\\w+``):

* **word accuracy** — share of ground-truth words matched in order (difflib alignment),
* **character similarity** — difflib ratio of the joined word sequences.
"""

from __future__ import annotations

import dataclasses
import difflib
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from tests.realcorpus import REAL_DIR
from tests.synthetic import _speckle
from tests.textutil import page_texts

FONT_DIR = Path(__file__).resolve().parent / "fixtures" / "fonts"
FONTS = ("DejaVuSans", "DejaVuSerif")
DPIS = (150, 200, 300)

ENGLISH_TEXT = """The quarterly report for the northern district was approved on 14 March 2025.
Revenue increased by 12.5 percent, while operating costs fell to 1,240 euros per unit.
Please send the signed contract, the invoice number 2025-0815 and a copy of your
identity card to our office before the end of the month. Questions about delivery,
payment terms or warranty claims are answered by the customer service team."""

GERMAN_TEXT = """Der Mietvertrag für die Wohnung in der Hauptstraße 12 beginnt am 1. Mai 2025.
Die monatliche Miete beträgt 850 Euro zuzüglich Nebenkosten für Heizung und Wasser.
Kündigungen müssen schriftlich und spätestens drei Monate vorher erfolgen. Größere
Schäden, zum Beispiel an Fenstern oder Türen, meldet der Mieter unverzüglich dem
Vermieter. Übergabe der Schlüssel erfolgt gegen Quittung."""

TEXTS = {"en": ENGLISH_TEXT, "de": GERMAN_TEXT}

BGBL_IMAGE_ONLY = REAL_DIR / "bgbl1950_nr5_page1_image_only_de.pdf"
BGBL_TEXT_LAYER = REAL_DIR / "bgbl1950_nr5_with_text_layer_de.pdf"


@dataclasses.dataclass(frozen=True, slots=True)
class Score:
    words: float
    chars: float
    missing: tuple[str, ...]

    def __str__(self) -> str:
        return f"words {self.words:.1%}, chars {self.chars:.1%}, missing {list(self.missing)}"


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def score(truth: str, recognized: str) -> Score:
    expected, found = words(truth), words(recognized)
    matcher = difflib.SequenceMatcher(None, expected, found, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    chars = difflib.SequenceMatcher(
        None, " ".join(expected), " ".join(found), autojunk=False
    ).ratio()
    missing = tuple(word for word in dict.fromkeys(expected) if word not in found)
    return Score(matched / len(expected), chars, missing)


def render_image(text: str, *, font: str, dpi: int) -> Image.Image:
    """An A4 page with ``text`` in ``font`` at about 11 pt, as scanned at ``dpi``."""
    width, height = int(8.27 * dpi), int(11.69 * dpi)
    page = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(page)
    size = dpi // 6
    face = ImageFont.truetype(str(FONT_DIR / f"{font}.ttf"), size)
    y = dpi
    for line in text.splitlines():
        draw.text((int(dpi * 0.8), y), line, fill=0, font=face)
        y += int(size * 1.6)
    return page


DEGRADATIONS = ("skewed", "noisy", "blurred", "low_contrast")


def degrade(page: Image.Image, variant: str) -> Image.Image:
    """The scanner defects of ``tests.synthetic.SCAN_VARIANTS`` applied to any page."""
    if variant == "skewed":
        return page.rotate(4, expand=True, fillcolor=255)
    if variant == "noisy":
        return _speckle(page, seed=7)
    if variant == "blurred":
        return page.filter(ImageFilter.GaussianBlur(1.2))
    if variant == "low_contrast":
        return page.point(lambda v: 110 + v * 90 // 255)
    raise ValueError(variant)


def render_pdf(path: Path, text: str, *, font: str, dpi: int, variant: str | None = None) -> Path:
    """An image-only PDF of :func:`render_image`, optionally with a scanner defect."""
    page = render_image(text, font=font, dpi=dpi)
    if variant is not None:
        page = degrade(page, variant)
    page.save(path, "PDF", resolution=dpi)
    return path


def bgbl_truth() -> str:
    """Page 1 text as published (the source PDF's own text layer)."""
    return page_texts(BGBL_TEXT_LAYER)[0]
