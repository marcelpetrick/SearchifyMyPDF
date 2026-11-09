# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""End-to-end workflow with the real OCR engine (A01, A02, A03, A06, A12)."""

import threading
from pathlib import Path

import pytest

from searchify_pdf.application.workflow import BatchRunner
from searchify_pdf.domain.jobs import JobEvent, JobState, Outcome
from searchify_pdf.domain.settings import ExistingOutputPolicy, Settings, WorkerMode
from searchify_pdf.engines.ocrmypdf_engine import OcrmypdfEngine
from tests import synthetic
from tests.textutil import all_text, contains_words, sha256

pytestmark = pytest.mark.ocr


def _tree(root: Path) -> dict[Path, str]:
    return {p: sha256(p) for p in root.rglob("*.pdf")}


def test_nested_unicode_folder_real_ocr(tmp_path: Path) -> None:
    deep = tmp_path / "Verträge 2025" / "Kunde Ä Ö"
    deep.mkdir(parents=True)
    synthetic.scanned_pdf(deep / "Rechnung Nr 1.pdf", (synthetic.GERMAN_LINES,))
    synthetic.scanned_pdf(tmp_path / "Invoice.PDF")
    synthetic.mixed_pdf(tmp_path / "Verträge 2025" / "mixed.pdf")
    originals = _tree(tmp_path)
    settings = Settings(worker_mode=WorkerMode.FIXED, fixed_workers=2)
    summary = BatchRunner(settings, OcrmypdfEngine(), version="t").run([tmp_path])
    assert summary.count(Outcome.CONVERTED) == 3, summary
    assert contains_words(all_text(deep / "Rechnung Nr 1_searchable.pdf"), ["Rechnung", "Vertrag"])
    assert contains_words(all_text(tmp_path / "Invoice_searchable.pdf"), ["invoice", "Payment"])
    assert {p: sha256(p) for p in originals} == originals  # originals unchanged
    assert not any(p.name.startswith(".") for p in tmp_path.rglob("*"))  # no leftovers
    again = BatchRunner(settings, OcrmypdfEngine(), version="t").run([tmp_path])
    assert again.count(Outcome.ACTION_REQUIRED) == 3  # Ask, but non-interactive


def test_cancel_real_engine_keeps_tree_clean(tmp_path: Path) -> None:
    for i in range(3):
        synthetic.scanned_pdf(tmp_path / f"{i}.pdf", [synthetic.ENGLISH_LINES] * 4, dpi=300)
    originals = _tree(tmp_path)
    cancel = threading.Event()

    def on_event(event: JobEvent) -> None:
        if event.state is JobState.RUNNING:
            threading.Timer(1.0, cancel.set).start()

    settings = Settings(
        worker_mode=WorkerMode.SEQUENTIAL,
        existing_output_policy=ExistingOutputPolicy.OVERWRITE,
    )
    summary = BatchRunner(settings, OcrmypdfEngine(), cancel=cancel, on_event=on_event).run(
        [tmp_path]
    )
    assert summary.count(Outcome.CANCELLED) >= 2
    assert _tree(tmp_path).keys() >= originals.keys()
    assert {p: sha256(p) for p in originals} == originals
    assert not any(p.name.startswith(".") for p in tmp_path.iterdir())
