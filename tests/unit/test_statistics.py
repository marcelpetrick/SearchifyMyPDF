# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Statistics semantics: true medians, no double counting, failure handling (A13)."""

import errno
import json
from pathlib import Path

import pytest

from searchify_pdf.domain.jobs import BatchSummary, JobResult, Outcome, PageCounts, Reason
from searchify_pdf.storage import statistics as mod
from searchify_pdf.storage.statistics import (
    STATS_FILE_NAME,
    Statistics,
    StatisticsError,
    StatisticsRepository,
    describe,
    record,
)


def _r(outcome: Outcome, seconds: float, ocr_pages: int = 2, queue: float = 0.5) -> JobResult:
    return JobResult(
        0,
        Path("/secret/client/contract.pdf"),
        None,
        outcome,
        Reason.OK,
        duration_seconds=seconds,
        queue_seconds=queue,
        pages=PageCounts(inspected=3, ocr_processed=ocr_pages, preserved=3 - ocr_pages),
    )


def test_describe_true_median() -> None:
    assert describe([]) is None
    d = describe([1.0, 2.0, 100.0])
    assert d is not None and (d.count, d.total, d.median) == (3, 103.0, 2.0)
    assert d.mean == pytest.approx(103 / 3)


def test_record_counts_and_excludes_failed_timings() -> None:
    summary = BatchSummary(
        (
            _r(Outcome.CONVERTED, 4.0),
            _r(Outcome.PRESERVED, 1.0, ocr_pages=0),
            _r(Outcome.FAILED, 99.0),
            _r(Outcome.CANCELLED, 50.0),
        ),
        wall_seconds=5.0,
    )
    stats = record(Statistics(), summary, ("eng", "deu"), "b1")
    assert stats.attempted == 4 and stats.processed == 2
    assert stats.outcomes == {"converted": 1, "preserved": 1, "failed": 1, "cancelled": 1}
    assert stats.pages["inspected"] == 12
    assert stats.languages == {"eng": 4, "deu": 4}
    assert stats.document_seconds == (4.0, 1.0)
    assert stats.page_estimate_seconds == (2.0,)
    assert stats.batch_wall_seconds == (5.0,)
    assert record(stats, summary, ("eng",), "b1") is stats  # same batch never counted twice
    assert record(stats, BatchSummary(()), ("eng",), "b2") is stats


def test_median_over_all_samples_not_batch_averages() -> None:
    a = BatchSummary(
        (_r(Outcome.CONVERTED, 1.0), _r(Outcome.CONVERTED, 1.0), _r(Outcome.CONVERTED, 1.0))
    )
    b = BatchSummary((_r(Outcome.CONVERTED, 10.0),))
    stats = record(record(Statistics(), a, ["eng"], "a"), b, ["eng"], "b")
    dist = describe(stats.document_seconds)
    assert dist is not None and dist.median == 1.0  # median of batch means would be 5.5


def test_samples_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "MAX_SAMPLES", 3)
    stats = Statistics()
    for i in range(5):
        stats = record(stats, BatchSummary((_r(Outcome.CONVERTED, float(i)),)), ["eng"], str(i))
    assert stats.document_seconds == (2.0, 3.0, 4.0)


def test_json_roundtrip_has_no_paths_or_text(tmp_path: Path) -> None:
    repo = StatisticsRepository(tmp_path)
    assert repo.load() == Statistics()
    assert repo.record_batch(BatchSummary((_r(Outcome.CONVERTED, 2.0),)), ["eng"], "x") == ""
    raw = (tmp_path / STATS_FILE_NAME).read_text()
    assert "secret" not in raw and "contract" not in raw
    loaded = repo.load()
    assert loaded.document_seconds == (2.0,)
    assert json.loads(raw)["schema_version"] == 1
    repo.reset()
    assert not (tmp_path / STATS_FILE_NAME).exists()
    repo.reset()  # idempotent


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"{bad", "json_invalid"),
        (b"[]", "schema_invalid"),
        (b'{"schema_version": 1, "attempted": "x"}', "value_invalid"),
    ],
)
def test_corrupt_file(tmp_path: Path, content: bytes, code: str) -> None:
    (tmp_path / STATS_FILE_NAME).write_bytes(content)
    repo = StatisticsRepository(tmp_path)
    with pytest.raises(StatisticsError) as info:
        repo.load()
    assert info.value.code == code
    assert repo.record_batch(BatchSummary((_r(Outcome.CONVERTED, 1.0),)), ["eng"]) == ""
    assert repo.load().attempted == 1


def test_write_and_read_failures_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = StatisticsRepository(tmp_path)

    def full(*_: object) -> None:
        raise OSError(errno.ENOSPC, "full")

    monkeypatch.setattr(mod, "atomic_write_bytes", full)
    assert repo.record_batch(BatchSummary((_r(Outcome.CONVERTED, 1.0),)), ["eng"]) == "disk_full"
    (tmp_path / STATS_FILE_NAME).mkdir()
    assert repo.record_batch(BatchSummary((_r(Outcome.CONVERTED, 1.0),)), ["eng"]) in {
        "write_failed",
        "permission_denied",
    }
    with pytest.raises(StatisticsError):
        repo.reset()
    assert str(StatisticsError("x")) == "x"
