# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
import os
from pathlib import Path

import pikepdf
import pytest

from searchify_pdf.application.discovery import discover
from searchify_pdf.domain.jobs import Reason
from searchify_pdf.engines import pdf_inspect, pdf_ops
from searchify_pdf.engines.pdf_inspect import (
    PdfInfo,
    PdfInspectionError,
    add_marker,
    count_pages,
    has_marker,
    inspect_pdf,
)
from tests import synthetic

SUFFIX = "_searchable"


# --- inspection ---------------------------------------------------------------------


def test_scanned_pdf_has_no_text(tmp_path: Path) -> None:
    info = inspect_pdf(synthetic.scanned_pdf(tmp_path / "s.pdf", (["a"], ["b"])))
    assert info.page_count == 2
    assert info.pages_with_text == (False, False)
    assert not info.any_text and not info.all_text
    assert not info.encrypted and not info.signed and not info.generated_marker


def test_digital_and_mixed(tmp_path: Path) -> None:
    digital = inspect_pdf(synthetic.digital_pdf(tmp_path / "d.pdf"))
    assert digital.all_text and digital.text_page_count == 1
    mixed = inspect_pdf(synthetic.mixed_pdf(tmp_path / "m.pdf"))
    assert mixed.pages_with_text == (True, False)
    assert mixed.any_text and not mixed.all_text


def test_empty_info_is_not_all_text() -> None:
    assert not PdfInfo(0, ()).all_text


def test_encrypted_with_user_password(tmp_path: Path) -> None:
    with pytest.raises(PdfInspectionError) as info:
        inspect_pdf(synthetic.encrypted_pdf(tmp_path / "e.pdf"))
    assert info.value.reason is Reason.PASSWORD_REQUIRED


def test_encrypted_owner_only_is_flagged(tmp_path: Path) -> None:
    info = inspect_pdf(synthetic.encrypted_pdf(tmp_path / "e.pdf", user_password=""))
    assert info.encrypted and info.protection is not None and info.protection.restricted_only
    assert info.pages_with_text == (False,)


def test_signed(tmp_path: Path) -> None:
    assert inspect_pdf(synthetic.signed_pdf(tmp_path / "sig.pdf")).signed


def _with_root(tmp_path: Path, **entries: object) -> Path:
    path = synthetic.scanned_pdf(tmp_path / "x.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        for key, value in entries.items():
            pdf.Root[f"/{key}"] = value
        pdf.save(path)
    return path


def test_signature_variants(tmp_path: Path) -> None:
    assert inspect_pdf(_with_root(tmp_path, Perms=pikepdf.Dictionary())).signed
    assert inspect_pdf(_with_root(tmp_path, AcroForm=pikepdf.Dictionary(SigFlags=3))).signed
    assert not inspect_pdf(_with_root(tmp_path, AcroForm=pikepdf.Dictionary(SigFlags=0))).signed
    assert not inspect_pdf(_with_root(tmp_path, AcroForm=pikepdf.Array([]))).signed
    unsigned_field = pikepdf.Dictionary(FT=pikepdf.Name.Sig)
    kids = pikepdf.Dictionary(Kids=pikepdf.Array([unsigned_field, 5]))
    assert not inspect_pdf(
        _with_root(tmp_path, AcroForm=pikepdf.Dictionary(Fields=pikepdf.Array([kids])))
    ).signed
    signed_kid = pikepdf.Dictionary(
        Kids=pikepdf.Array([pikepdf.Dictionary(FT=pikepdf.Name.Sig, V=1)])
    )
    assert inspect_pdf(
        _with_root(tmp_path, AcroForm=pikepdf.Dictionary(Fields=pikepdf.Array([signed_kid])))
    ).signed


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda p: synthetic.corrupt_pdf(p), Reason.INVALID_PDF),
        (lambda p: p, Reason.NOT_FOUND),
    ],
)
def test_invalid_inputs(tmp_path: Path, make: object, reason: Reason) -> None:
    path = make(tmp_path / "bad.pdf")  # type: ignore[operator]
    with pytest.raises(PdfInspectionError) as info:
        inspect_pdf(path)
    assert info.value.reason is reason
    assert reason.value in str(info.value)


@pytest.mark.skipif(
    os.name == "nt" or os.geteuid() == 0, reason="POSIX permissions; root ignores them"
)
def test_unreadable(tmp_path: Path) -> None:
    path = synthetic.scanned_pdf(tmp_path / "u.pdf")
    path.chmod(0)
    try:
        with pytest.raises(PdfInspectionError) as info:
            inspect_pdf(path)
        assert info.value.reason is Reason.UNREADABLE
    finally:
        path.chmod(0o644)


def test_pdfium_failure_is_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = synthetic.scanned_pdf(tmp_path / "s.pdf")

    def boom(_: bytes, _password: str = "") -> list[bool]:
        raise pdf_ops.pypdfium2.PdfiumError("bad")

    monkeypatch.setattr(pdf_inspect, "backend", pdf_inspect.InProcess)
    monkeypatch.setattr(pdf_ops, "page_text_flags", boom)
    with pytest.raises(PdfInspectionError) as info:
        inspect_pdf(path)
    assert info.value.reason is Reason.INVALID_PDF
    assert str(PdfInspectionError(Reason.OK)) == "ok"


def test_marker_roundtrip(tmp_path: Path) -> None:
    path = synthetic.scanned_pdf(tmp_path / "s.pdf")
    assert not has_marker(path)
    add_marker(path, "1.2.3")
    assert has_marker(path)
    assert inspect_pdf(path).generated_marker
    assert count_pages(path) == 1
    assert not has_marker(synthetic.corrupt_pdf(tmp_path / "c.pdf"))
    assert not has_marker(tmp_path / "missing.pdf")


# --- discovery ----------------------------------------------------------------------


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n")
    return path


def _no_marker(_: Path) -> bool:
    return False


def test_recursive_adjacent_destinations(tmp_path: Path) -> None:
    a = _touch(tmp_path / "Contracts" / "2025" / "Acme.pdf")
    b = _touch(tmp_path / "Contracts" / "Grüße mit Leerzeichen.PDF")
    _touch(tmp_path / "Contracts" / "notes.txt")
    result = discover([tmp_path], SUFFIX, [SUFFIX], _no_marker)
    pairs = {(c.source, c.destination) for c in result.candidates}
    assert pairs == {
        (a, a.with_name("Acme_searchable.pdf")),
        (b, b.with_name("Grüße mit Leerzeichen_searchable.pdf")),
    }
    assert result.omissions == ()
    assert not (tmp_path / "output").exists()


def test_generated_copies_excluded_but_originals_kept(tmp_path: Path) -> None:
    src = _touch(tmp_path / "Acme.pdf")
    gen = _touch(tmp_path / "Acme_searchable.pdf")
    natural = _touch(tmp_path / "Report_searchable.pdf")
    old = _touch(tmp_path / "Old_ocr.pdf")
    markers = {gen}
    result = discover([tmp_path], SUFFIX, [SUFFIX, "_ocr"], lambda p: p in markers)
    assert [c.source for c in result.candidates] == [src]
    reasons = {o.path: o.reason for o in result.omissions}
    assert reasons == {
        gen: Reason.GENERATED_COPY,
        natural: Reason.LOOKS_GENERATED,
        old: Reason.LOOKS_GENERATED,
    }


def test_explicit_override_for_natural_suffix(tmp_path: Path) -> None:
    natural = _touch(tmp_path / "Report_searchable.pdf")
    result = discover([natural], SUFFIX, [SUFFIX], _no_marker)
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.explicit and candidate.looks_generated
    assert candidate.destination.name == "Report_searchable_searchable.pdf"
    marked = discover([natural], SUFFIX, [SUFFIX], lambda _: True)
    assert marked.candidates == ()
    assert marked.omissions[0].reason is Reason.GENERATED_COPY


def test_missing_and_non_pdf_inputs(tmp_path: Path) -> None:
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    result = discover([tmp_path / "nope.pdf", txt], SUFFIX, [SUFFIX], _no_marker)
    assert [o.reason for o in result.omissions] == [Reason.NOT_FOUND, Reason.NOT_PDF]


def test_symlinks_not_followed_in_folders(tmp_path: Path) -> None:
    real = _touch(tmp_path / "real" / "a.pdf")
    root = tmp_path / "root"
    root.mkdir()
    (root / "linkdir").symlink_to(tmp_path / "real", target_is_directory=True)
    (root / "link.pdf").symlink_to(real)
    (root / "loop").symlink_to(root, target_is_directory=True)
    result = discover([root], SUFFIX, [SUFFIX], _no_marker)
    assert result.candidates == ()
    assert {o.reason for o in result.omissions} == {Reason.SYMLINK}
    assert len(result.omissions) == 3
    explicit = discover([root / "link.pdf"], SUFFIX, [SUFFIX], _no_marker)
    assert len(explicit.candidates) == 1


def test_duplicates_deduplicated(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.pdf")
    result = discover([a, tmp_path, tmp_path / "." / "a.pdf"], SUFFIX, [SUFFIX], _no_marker)
    assert [c.source for c in result.candidates] == [a]


def test_case_only_destination_collision(tmp_path: Path) -> None:
    upper = _touch(tmp_path / "Scan.pdf")
    lower = _touch(tmp_path / "scan.PDF")
    if upper.samefile(lower):  # case-insensitive filesystem
        pytest.skip("filesystem is case-insensitive")
    result = discover([tmp_path], SUFFIX, [SUFFIX], _no_marker)
    assert len(result.candidates) == 1
    assert result.omissions[0].reason is Reason.DESTINATION_COLLISION


def test_destination_collides_with_explicit_source(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.pdf")
    natural = _touch(tmp_path / "a_searchable.pdf")
    result = discover([a, natural], SUFFIX, [SUFFIX], _no_marker)
    assert [c.source for c in result.candidates] == [natural]
    assert result.omissions[0].path == a
    assert result.omissions[0].reason is Reason.DESTINATION_COLLISION


@pytest.mark.skipif(
    os.name == "nt" or os.geteuid() == 0, reason="POSIX permissions; root ignores them"
)
def test_unreadable_subfolder_reported(tmp_path: Path) -> None:
    ok = _touch(tmp_path / "ok.pdf")
    locked = tmp_path / "locked"
    _touch(locked / "hidden.pdf")
    locked.chmod(0)
    try:
        result = discover([tmp_path], SUFFIX, [SUFFIX], _no_marker)
    finally:
        locked.chmod(0o755)
    assert [c.source for c in result.candidates] == [ok]
    assert result.omissions[0].reason is Reason.UNREADABLE


def test_long_unicode_paths(tmp_path: Path) -> None:
    deep = tmp_path
    for i in range(12):
        deep = deep / f"Ordner {i} — ünïcødé"
    src = _touch(deep / ("x" * 150 + ".pdf"))
    result = discover([tmp_path], SUFFIX, [SUFFIX], _no_marker)
    assert result.candidates[0].source == src


def test_staging_files_ignored(tmp_path: Path) -> None:
    _touch(tmp_path / ".a_searchable.pdf.abc.searchify-partial")
    _touch(tmp_path / ".a_searchable.pdf.searchify-lock")
    assert discover([tmp_path], SUFFIX, [SUFFIX], _no_marker).candidates == ()


def test_non_numeric_sigflags(tmp_path: Path) -> None:
    path = _with_root(tmp_path, AcroForm=pikepdf.Dictionary(SigFlags=pikepdf.Name.Bad))
    assert not inspect_pdf(path).signed
