# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Synthetic PDF fixtures with known content (no personal documents, VISION §11).

* ``scanned_pdf`` — image-only pages rendered from text (what a scanner produces).
* ``digital_pdf`` — born-digital pages with a real text layer (Helvetica).
* ``mixed_pdf`` — digital page(s) followed by scanned page(s).
* ``encrypted_pdf``, ``signed_pdf``, ``corrupt_pdf`` — adversarial inputs.

Expected words are plain ASCII so OCR assertions do not depend on font glyph coverage.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pikepdf
from PIL import Image, ImageDraw, ImageFont

ENGLISH_LINES = ("Searchable invoice alpha", "Payment due within thirty days")
GERMAN_LINES = ("Rechnung Vertrag Kunde", "Zahlung innerhalb dreissig Tage")
DIGITAL_LINES = ("Digital contract preface", "Born digital text layer")


def render_page(lines: Sequence[str], *, dpi: int = 150, rotate: int = 0) -> Image.Image:
    width, height = int(8.27 * dpi), int(11.69 * dpi)  # A4
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(12, dpi // 3))
    y = dpi
    for line in lines:
        draw.text((dpi, y), line, fill=0, font=font)
        y += dpi // 2
    if rotate:
        image = image.rotate(rotate, expand=True, fillcolor=255)
    return image


def scanned_pdf(
    path: Path,
    pages: Sequence[Sequence[str]] = (ENGLISH_LINES,),
    *,
    dpi: int = 150,
    rotate: int = 0,
) -> Path:
    images = [render_page(lines, dpi=dpi, rotate=rotate) for lines in pages]
    images[0].save(path, "PDF", resolution=dpi, save_all=True, append_images=images[1:])
    return path


def _digital_page(pdf: pikepdf.Pdf, lines: Sequence[str]) -> pikepdf.Page:
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
        )
    )
    ops = ["BT", "/F1 24 Tf", "72 760 Td"]
    for line in lines:
        ops.append(f"({line}) Tj")
        ops.append("0 -36 Td")
    ops.append("ET")
    page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=[0, 0, 595, 842],
        Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font)),
        Contents=pdf.make_stream("\n".join(ops).encode()),
    )
    return pikepdf.Page(page)


def digital_pdf(path: Path, pages: Sequence[Sequence[str]] = (DIGITAL_LINES,)) -> Path:
    pdf = pikepdf.new()
    for lines in pages:
        pdf.pages.append(_digital_page(pdf, lines))
    pdf.save(path)
    return path


def mixed_pdf(
    path: Path, digital: Sequence[str] = DIGITAL_LINES, scanned: Sequence[str] = ENGLISH_LINES
) -> Path:
    scan = scanned_pdf(path.with_name(f".{path.name}.scan.pdf"), (scanned,))
    pdf = pikepdf.new()
    pdf.pages.append(_digital_page(pdf, digital))
    with pikepdf.open(scan) as scanned_doc:
        pdf.pages.extend(scanned_doc.pages)
        pdf.save(path)
    scan.unlink()
    return path


def encrypted_pdf(path: Path, user_password: str = "secret") -> Path:
    scan = scanned_pdf(path.with_name(f".{path.name}.plain.pdf"))
    with pikepdf.open(scan) as pdf:
        pdf.save(path, encryption=pikepdf.Encryption(owner="owner", user=user_password))
    scan.unlink()
    return path


def signed_pdf(path: Path) -> Path:
    """A PDF with a filled signature field (no real cryptography needed for detection)."""
    scan = scanned_pdf(path.with_name(f".{path.name}.plain.pdf"))
    with pikepdf.open(scan) as pdf:
        sig_value = pdf.make_indirect(
            pikepdf.Dictionary(Type=pikepdf.Name.Sig, Filter=pikepdf.Name("/Adobe.PPKLite"))
        )
        field = pdf.make_indirect(
            pikepdf.Dictionary(FT=pikepdf.Name.Sig, T=pikepdf.String("Signature1"), V=sig_value)
        )
        pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([field]))
        pdf.save(path)
    scan.unlink()
    return path


def corrupt_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.7\nthis is not really a pdf\n%%EOF\n")
    return path
