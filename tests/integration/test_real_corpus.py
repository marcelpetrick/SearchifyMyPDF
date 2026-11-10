# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""The full workflow on real-life public-domain / CC scans (A01, A02, A05, VISION §5)."""

from pathlib import Path

import pytest

from searchify_pdf.application.workflow import BatchRunner
from searchify_pdf.domain.jobs import Outcome, Reason
from searchify_pdf.domain.settings import ExistingTextPolicy, Settings, WorkerMode
from searchify_pdf.engines.ocrmypdf_engine import OcrmypdfEngine
from tests import realcorpus
from tests.textutil import all_text, contains_words, page_texts, sha256

pytestmark = pytest.mark.ocr


def test_manifest_matches_the_files() -> None:
    from searchify_pdf.engines.pdf_inspect import inspect_pdf

    for doc in realcorpus.documents():
        info = inspect_pdf(doc.path)
        assert info.encrypted is doc.protected, doc.file
        assert info.page_count == doc.pages, doc.file
        assert any(info.pages_with_text) is doc.text_layer, doc.file


def test_real_corpus_default_settings(tmp_path: Path) -> None:
    docs = realcorpus.copy_corpus(tmp_path)
    originals = {p: sha256(p) for p in tmp_path.iterdir()}
    settings = Settings(worker_mode=WorkerMode.FIXED, fixed_workers=2)
    summary = BatchRunner(settings, OcrmypdfEngine(), version="t").run([tmp_path])
    by_name = {r.source.name: r for r in summary.results}
    for doc in docs:
        result = by_name[doc.file]
        copy = tmp_path / doc.copy_name
        if doc.protected:
            assert (result.outcome, result.reason) == (Outcome.FAILED, Reason.RESTRICTED)
            assert not copy.exists()
        elif doc.text_layer:  # "keep existing text": every page has text → copied as is
            assert result.outcome is Outcome.PRESERVED, result
            assert page_texts(copy) == page_texts(doc.path)
        else:
            assert result.outcome is Outcome.CONVERTED, result
            assert contains_words(all_text(copy), doc.words), (doc.file, all_text(copy)[:400])
    assert {p: sha256(p) for p in originals} == originals
    assert not any(p.name.startswith(".") for p in tmp_path.iterdir())


def test_real_text_layer_is_replaced_on_request(tmp_path: Path) -> None:
    doc = next(d for d in realcorpus.documents() if d.text_layer)
    realcorpus.copy_corpus(tmp_path / "all")
    src = tmp_path / "all" / doc.file
    settings = Settings(existing_text_policy=ExistingTextPolicy.ALWAYS_REPLACE)
    summary = BatchRunner(settings, OcrmypdfEngine(), version="t").run([src])
    assert summary.count(Outcome.CONVERTED) == 1, summary
    copy = src.with_name(doc.copy_name)
    assert len(page_texts(copy)) == doc.pages
    assert contains_words(all_text(copy), doc.words)


def test_real_restricted_scan_is_processed_when_enabled(tmp_path: Path) -> None:
    """ADR 0011: opt-in; the copy is searchable and keeps exactly the source's restrictions."""
    import pikepdf

    doc = next(d for d in realcorpus.documents() if d.protected)
    realcorpus.copy_corpus(tmp_path / "all")
    src = tmp_path / "all" / doc.file
    before = sha256(src)
    settings = Settings(process_restricted_pdfs=True)
    result = BatchRunner(settings, OcrmypdfEngine(), version="t").run([src]).results[0]
    assert result.outcome is Outcome.CONVERTED, result
    copy = src.with_name(doc.copy_name)
    assert contains_words(all_text(copy), doc.words), all_text(copy)[:400]
    with pikepdf.open(src) as original, pikepdf.open(copy) as protected:
        assert protected.is_encrypted and not protected.owner_password_matched
        assert protected.allow == original.allow
    assert sha256(src) == before


def test_synthetic_owner_restricted_pdf_is_rejected_like_the_real_one(tmp_path: Path) -> None:
    from tests import synthetic

    src = synthetic.restricted_pdf(tmp_path / "restricted.pdf")
    summary = BatchRunner(Settings(), OcrmypdfEngine(), version="t").run([src])
    result = summary.results[0]
    assert (result.outcome, result.reason) == (Outcome.FAILED, Reason.RESTRICTED)


def test_password_protected_scan_gets_a_password_protected_searchable_copy(
    tmp_path: Path,
) -> None:
    """ADR 0011: real OCR on a decrypted private copy; the copy needs the same password."""
    import pikepdf

    from tests import synthetic

    src = synthetic.encrypted_pdf(tmp_path / "Statement.pdf")
    before = sha256(src)
    summary = BatchRunner(Settings(), OcrmypdfEngine(), version="t", passwords=["secret"]).run(
        [src]
    )
    assert summary.count(Outcome.CONVERTED) == 1, summary
    copy = tmp_path / "Statement_searchable.pdf"
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(copy)
    assert contains_words(all_text(copy, "secret"), list(synthetic.ENGLISH_LINES[0].split()))
    assert sha256(src) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Statement.pdf", copy.name]


def test_long_document_keeps_every_page(tmp_path: Path) -> None:
    from tests import synthetic

    src = synthetic.long_scanned_pdf(tmp_path / "long.pdf", pages=40)
    settings = Settings(worker_mode=WorkerMode.FIXED, fixed_workers=2)
    summary = BatchRunner(settings, OcrmypdfEngine(), version="t").run([src])
    assert summary.count(Outcome.CONVERTED) == 1, summary
    texts = page_texts(tmp_path / "long_searchable.pdf")
    assert len(texts) == 40
    assert sum("Page" in t for t in texts) >= 38
