# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from searchify_pdf.domain.jobs import (
    BatchSummary,
    JobResult,
    Outcome,
    Reason,
)
from searchify_pdf.domain.paths import (
    collision_key,
    is_pdf_name,
    lock_path_for,
    looks_generated,
    output_path_for,
    staging_path_for,
)

SUFFIX = "_searchable"


def test_output_path_is_adjacent() -> None:
    src = Path("Contracts/2025/Acme.pdf")
    assert output_path_for(src, SUFFIX) == Path("Contracts/2025/Acme_searchable.pdf")
    assert output_path_for(Path("x/Scan.PDF"), SUFFIX) == Path("x/Scan_searchable.pdf")
    assert output_path_for(Path("a b/Grüße.v2.pdf"), SUFFIX) == Path("a b/Grüße.v2_searchable.pdf")


names = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="/\\\x00."),
    min_size=1,
    max_size=40,
)


@given(stem=names, folder=names)
def test_output_never_equals_source_and_stays_in_folder(stem: str, folder: str) -> None:
    src = Path(folder) / f"{stem}.pdf"
    out = output_path_for(src, SUFFIX)
    assert out != src
    assert out.parent == src.parent
    assert out.name.endswith(".pdf")
    assert looks_generated(out, [SUFFIX])


@given(stem=names)
def test_generated_is_not_regenerated_twice(stem: str) -> None:
    once = output_path_for(Path(f"{stem}.pdf"), SUFFIX)
    assert looks_generated(once, [SUFFIX])


def test_is_pdf_name() -> None:
    assert is_pdf_name(Path("a.pdf"))
    assert is_pdf_name(Path("A.PdF"))
    assert not is_pdf_name(Path(".pdf"))
    assert not is_pdf_name(Path("a.pdf.txt"))
    assert not is_pdf_name(Path("a.txt"))
    assert not is_pdf_name(staging_path_for(Path("d/a_searchable.pdf"), "abc"))
    assert not is_pdf_name(Path(".a.pdf.searchify-lock.pdf"))


def test_looks_generated() -> None:
    assert looks_generated(Path("Acme_searchable.pdf"), [SUFFIX])
    assert looks_generated(Path("Acme_SEARCHABLE.PDF"), [SUFFIX])
    assert looks_generated(Path("Acme_ocr.pdf"), [SUFFIX, "_ocr"])
    assert not looks_generated(Path("Acme.pdf"), [SUFFIX])
    assert not looks_generated(Path("_searchable.pdf"), [SUFFIX])
    assert not looks_generated(Path("Acme_ocr.pdf"), [SUFFIX])


def test_temp_and_lock_paths_are_hidden_siblings() -> None:
    dest = Path("d/Acme_searchable.pdf")
    staging = staging_path_for(dest, "tok")
    lock = lock_path_for(dest)
    assert staging.parent == lock.parent == dest.parent
    assert staging.name.startswith(".") and lock.name.startswith(".")
    assert "tok" in staging.name
    assert collision_key(Path("A/B.pdf")) == collision_key(Path("a/b.PDF"))


def _r(outcome: Outcome, dest: Path | None = Path("d/x_searchable.pdf")) -> JobResult:
    return JobResult(1, Path("d/x.pdf"), dest, outcome, Reason.OK)


def test_summary_counts_and_success() -> None:
    summary = BatchSummary(
        (
            _r(Outcome.CONVERTED),
            _r(Outcome.PRESERVED, Path("e/y_searchable.pdf")),
            _r(Outcome.SKIPPED),
        )
    )
    assert summary.count(Outcome.CONVERTED) == 1
    assert summary.counts[Outcome.FAILED] == 0
    assert summary.succeeded
    assert summary.folders == (Path("d"), Path("e"))
    for bad in (Outcome.FAILED, Outcome.CANCELLED, Outcome.ACTION_REQUIRED):
        assert not BatchSummary((_r(bad),)).succeeded


def test_summary_folders_ignore_unwritten() -> None:
    summary = BatchSummary((_r(Outcome.FAILED), _r(Outcome.CONVERTED, None), _r(Outcome.CONVERTED)))
    assert summary.folders == (Path("d"),)
