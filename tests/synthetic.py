# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Synthetic PDF fixtures with known content (no personal documents, VISION §11).

* ``scanned_pdf`` — image-only pages rendered from text (what a scanner produces).
* ``digital_pdf`` — born-digital pages with a real text layer (Helvetica).
* ``mixed_pdf`` — digital page(s) followed by scanned page(s).
* ``ocr_layer_pdf`` — a scan with an invisible earlier-OCR text layer, correct or garbled.
* ``degraded_scan_pdf`` — realistic scanner defects: skew, noise, blur, low contrast,
  low resolution, landscape, two columns, upside-down pages (``SCAN_VARIANTS``).
* ``long_scanned_pdf`` — many pages (throughput, progress).
* ``encrypted_pdf``, ``restricted_pdf`` (owner password only), ``signed_pdf``,
  ``corrupt_pdf`` — adversarial inputs.

Expected words are plain ASCII so OCR assertions do not depend on font glyph coverage.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pikepdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

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


LEFT_COLUMN = ("Quarterly report north", "Revenue increased steadily")
RIGHT_COLUMN = ("Inventory audit south", "Shipment arrived Monday")
SCAN_VARIANTS = (
    "skewed",
    "noisy",
    "blurred",
    "low_contrast",
    "low_resolution",
    "landscape",
    "two_columns",
    "upside_down",
)


def _speckle(image: Image.Image, seed: int, amount: float = 0.02) -> Image.Image:
    """Deterministic salt-and-pepper noise (no global random state)."""
    noisy = image.copy()
    pixels = noisy.load()
    assert pixels is not None
    width, height = noisy.size
    state = seed or 1
    for _ in range(int(width * height * amount)):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF  # tiny LCG
        x, y = state % width, (state >> 8) % height
        pixels[x, y] = 0 if state & 1 else 255
    return noisy


def degraded_image(variant: str, *, dpi: int = 200) -> Image.Image:
    """One scanned page with a typical defect; the text is always ``ENGLISH_LINES``."""
    if variant == "skewed":
        return render_page(ENGLISH_LINES, dpi=dpi, rotate=4)
    if variant == "noisy":
        return _speckle(render_page(ENGLISH_LINES, dpi=dpi), seed=7)
    if variant == "blurred":
        return render_page(ENGLISH_LINES, dpi=dpi).filter(ImageFilter.GaussianBlur(1.2))
    if variant == "low_contrast":  # grey text on grey paper
        return render_page(ENGLISH_LINES, dpi=dpi).point(lambda v: 110 + v * 90 // 255)
    if variant == "low_resolution":
        return render_page(ENGLISH_LINES, dpi=100)
    if variant == "landscape":
        portrait = render_page(ENGLISH_LINES, dpi=dpi)
        landscape = Image.new("L", (portrait.height, portrait.width), 255)
        landscape.paste(portrait.crop((0, 0, portrait.width, portrait.width // 2)), (0, 0))
        return landscape
    if variant == "two_columns":
        page = render_page((), dpi=dpi)
        draw = ImageDraw.Draw(page)
        font = ImageFont.load_default(size=max(12, dpi // 4))
        for column, lines in enumerate((LEFT_COLUMN, RIGHT_COLUMN)):
            for row, line in enumerate(lines):
                draw.text(
                    (dpi // 2 + column * page.width // 2, dpi + row * dpi // 2), line, 0, font
                )
        return page
    if variant == "upside_down":
        # Orientation detection needs natural text: synthetic one-font lines stay below
        # OCRmyPDF's confidence threshold, so a real public-domain memo is turned around.
        import pypdfium2

        from tests.realcorpus import REAL_DIR

        doc = pypdfium2.PdfDocument(str(REAL_DIR / "lbj1964_maddox_memo_typewritten.pdf"))
        try:
            page = doc[0].render(scale=dpi / 72).to_pil().convert("L")
        finally:
            doc.close()
        return page.rotate(180)
    raise ValueError(variant)


def expected_words(variant: str) -> tuple[str, ...]:
    if variant == "two_columns":
        return ("Quarterly", "Revenue", "Inventory", "Shipment")
    if variant == "upside_down":
        return ("Maddox", "Tonkin", "Captain", "President")
    return ("Searchable", "invoice", "Payment", "thirty")


def degraded_scan_pdf(path: Path, variant: str) -> Path:
    image = degraded_image(variant)
    dpi = 100 if variant == "low_resolution" else 200
    image.save(path, "PDF", resolution=dpi)
    return path


def long_scanned_pdf(path: Path, pages: int = 40) -> Path:
    """A long scan whose page ``n`` says ``Page n``; rendered at a modest resolution."""
    lines = [(f"Page {n} of {pages}", "Searchable invoice alpha") for n in range(1, pages + 1)]
    return scanned_pdf(path, lines, dpi=100)


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


REPORT_LINES = (
    "Quarterly report for the northern district",
    "Revenue increased while operating costs fell",
    "Please send the signed contract and invoice",
)
GARBLED_LINES = (
    "Qnartcrly rcp0rt f0r tbe n0rtbcrn d1strict",
    "Rcvcnuc 1ncrcascd wb1lc 0pcrat1ng c0sts fcll",
    "Plcasc scnd tbc s1gncd c0ntract aud 1nv01cc",
)


def ocr_layer_pdf(
    path: Path,
    image_lines: Sequence[str] = REPORT_LINES,
    layer_lines: Sequence[str] = REPORT_LINES,
) -> Path:
    """A scan with an invisible OCR text layer (text render mode 3), like earlier OCR.

    ``layer_lines`` different from ``image_lines`` model a poor earlier recognition.
    """
    scan = scanned_pdf(path.with_name(f".{path.name}.scan.pdf"), (image_lines,), dpi=200)
    with pikepdf.open(scan) as pdf:
        page = pdf.pages[0]
        font = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
            )
        )
        resources = page.obj.Resources
        if pikepdf.Name.Font not in resources:
            resources.Font = pikepdf.Dictionary()
        resources.Font.FOCR = font
        ops = ["BT", "3 Tr", "/FOCR 14 Tf", "72 760 Td"]
        for line in layer_lines:
            ops += [f"({line}) Tj", "0 -24 Td"]
        ops.append("ET")
        page.contents_add(pdf.make_stream("\n".join(ops).encode()), prepend=False)
        pdf.save(path)
    scan.unlink()
    return path


def encrypted_pdf(path: Path, user_password: str = "secret") -> Path:
    scan = scanned_pdf(path.with_name(f".{path.name}.plain.pdf"))
    with pikepdf.open(scan) as pdf:
        pdf.save(path, encryption=pikepdf.Encryption(owner="owner", user=user_password))
    scan.unlink()
    return path


def restricted_pdf(path: Path) -> Path:
    """Opens without a password, but an owner password forbids extracting and modifying.

    The most common protection on archive scans (e.g. the NDL fixture in ``fixtures/real``).
    """
    scan = scanned_pdf(path.with_name(f".{path.name}.plain.pdf"))
    with pikepdf.open(scan) as pdf:
        pdf.save(
            path,
            encryption=pikepdf.Encryption(
                owner="owner",
                user="",
                allow=pikepdf.Permissions(extract=False, modify_other=False),
            ),
        )
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
