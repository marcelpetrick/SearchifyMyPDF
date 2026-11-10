# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Assertions added after reviewing surviving mutants (see docs/mutation-baseline.md)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from searchify_pdf.application import scheduler
from searchify_pdf.application.discovery import discover
from searchify_pdf.domain.jobs import BatchSummary, JobResult, Outcome, PageCounts, Reason
from searchify_pdf.domain.settings import (
    SCHEMA_VERSION,
    Settings,
    SettingsError,
    from_json,
    migrate,
)
from searchify_pdf.storage import publisher
from searchify_pdf.storage.publisher import PublishError, new_staging_path, publish, validate_output
from searchify_pdf.storage.settings_repository import (
    SETTINGS_FILE_NAME,
    LoadStatus,
    SettingsRepository,
    SettingsSaveError,
)
from searchify_pdf.storage.statistics import (
    STATS_FILE_NAME,
    Statistics,
    StatisticsError,
    StatisticsRepository,
    record,
)
from tests import synthetic


@pytest.mark.parametrize(
    ("changes", "detail"),
    [
        ({"ocr_languages": ("EN",)}, "'EN'"),
        ({"output_suffix": "a/b"}, "'a/b'"),
        ({"previous_suffixes": ("x.pdf",)}, "'x.pdf'"),
        ({"fixed_workers": 0}, "0"),
        ({"timeout_seconds": 5}, "5"),
        ({"deskew": "yes"}, "'yes'"),
        ({"theme": "dark"}, "'dark'"),
    ],
)
def test_settings_error_details_name_the_value(changes: dict[str, Any], detail: str) -> None:
    with pytest.raises(SettingsError) as info:
        Settings(**changes)
    assert info.value.detail == detail
    assert str(info.value) == f"{info.value.code}: {detail}"


def test_from_json_error_details() -> None:
    with pytest.raises(SettingsError) as info:
        from_json([1])
    assert info.value.detail == "list"
    with pytest.raises(SettingsError) as info:
        from_json({"theme": "neon"})
    assert info.value.detail == "theme='neon'"
    with pytest.raises(SettingsError) as info:
        from_json({"previous_suffixes": "x"})
    assert info.value.detail == "previous_suffixes"
    with pytest.raises(SettingsError) as info:
        migrate({"schema_version": SCHEMA_VERSION + 4})
    assert info.value.detail == str(SCHEMA_VERSION + 4)
    with pytest.raises(SettingsError) as info:
        migrate({"schema_version": "x"})
    assert info.value.detail == "'x'"


def test_to_json_is_complete_and_exact() -> None:
    data = Settings().with_changes(output_suffix="_ocr").to_json()
    assert data == {
        "schema_version": SCHEMA_VERSION,
        "ocr_languages": ["eng", "deu"],
        "deskew": False,
        "rotate_pages": False,
        "existing_text_policy": "never_replace",
        "existing_output_policy": "ask",
        "output_suffix": "_ocr",
        "previous_suffixes": ["_searchable"],
        "worker_mode": "auto",
        "fixed_workers": 2,
        "statistics_enabled": False,
        "theme": "system",
        "ui_language": "en",
        "timeout_seconds": 1800,
        "process_restricted_pdfs": False,
    }
    assert migrate({"schema_version": 1})["schema_version"] == SCHEMA_VERSION
    assert migrate({})["previous_suffixes"] == []
    assert migrate({"schema_version": 2, "previous_suffixes": ["_a"]})["previous_suffixes"] == [
        "_a"
    ]


def test_statistics_roundtrip_is_lossless(tmp_path: Path) -> None:
    stats = Statistics(
        attempted=5,
        outcomes={"converted": 3, "failed": 2},
        pages={"inspected": 9, "ocr_processed": 7},
        languages={"eng": 5, "deu": 5},
        document_seconds=(1.23456, 2.0),
        page_estimate_seconds=(0.5,),
        queue_seconds=(0.1, 0.2),
        batch_wall_seconds=(3.0,),
        batch_ids=("a", "b"),
    )
    data = stats.to_json()
    assert data["document_seconds"] == [1.2346, 2.0]
    assert data["batch_ids"] == ["a", "b"] and data["schema_version"] == 1
    back = Statistics.from_json(json.loads(json.dumps(data)))
    assert back.attempted == 5 and back.outcomes == stats.outcomes and back.pages == stats.pages
    assert back.languages == stats.languages and back.page_estimate_seconds == (0.5,)
    assert back.queue_seconds == (0.1, 0.2) and back.batch_wall_seconds == (3.0,)
    assert back.batch_ids == ("a", "b") and back.document_seconds == (1.2346, 2.0)
    assert Statistics.from_json({"schema_version": 1}) == Statistics()
    repo = StatisticsRepository(tmp_path)
    repo.save(stats)
    assert repo.path == tmp_path / STATS_FILE_NAME
    assert repo.load().batch_ids == ("a", "b")


def test_statistics_error_codes(tmp_path: Path) -> None:
    with pytest.raises(StatisticsError) as info:
        Statistics.from_json({"schema_version": 2})
    assert info.value.code == "schema_invalid"
    with pytest.raises(StatisticsError) as info:
        Statistics.from_json({"schema_version": 1, "document_seconds": ["x"]})
    assert info.value.code == "value_invalid" and "x" in str(info.value)
    (tmp_path / STATS_FILE_NAME).write_bytes(b"\xff")
    with pytest.raises(StatisticsError) as info:
        StatisticsRepository(tmp_path).load()
    assert info.value.code == "json_invalid"
    (tmp_path / STATS_FILE_NAME).unlink()
    (tmp_path / STATS_FILE_NAME).mkdir()
    with pytest.raises(StatisticsError) as info:
        StatisticsRepository(tmp_path).load()
    assert info.value.code in {"write_failed", "permission_denied"}
    with pytest.raises(StatisticsError) as info:
        StatisticsRepository(tmp_path).reset()
    assert info.value.code in {"write_failed", "permission_denied"}
    assert str(StatisticsError("a", "b")) == "a: b"


def test_record_ignores_queue_of_failed_and_estimates_only_ocr_pages() -> None:
    def result(outcome: Outcome, seconds: float, ocr: int) -> JobResult:
        return JobResult(
            0,
            Path("x"),
            None,
            outcome,
            Reason.OK,
            "",
            seconds,
            7.0,
            PageCounts(4, ocr, 4 - ocr, 0, 0),
        )

    summary = BatchSummary(
        (
            result(Outcome.CONVERTED, 8.0, 4),
            result(Outcome.PRESERVED, 2.0, 0),
            result(Outcome.SKIPPED, 9.0, 0),
        ),
        wall_seconds=6.0,
    )
    stats = record(Statistics(), summary, ["eng"], "id")
    assert stats.queue_seconds == (7.0, 7.0)
    assert stats.page_estimate_seconds == (2.0,)
    assert stats.pages == {
        "inspected": 12,
        "ocr_processed": 4,
        "preserved": 8,
        "skipped": 0,
        "failed": 0,
    }
    assert stats.batch_ids == ("id",)
    assert stats.processed == 2


def test_record_batch_preserves_existing_statistics(tmp_path: Path) -> None:
    repo = StatisticsRepository(tmp_path)
    one = BatchSummary(
        (JobResult(0, Path("x"), None, Outcome.CONVERTED, Reason.OK, duration_seconds=1.0),)
    )
    assert repo.record_batch(one, ["eng"], "first") == ""
    assert repo.record_batch(one, ["eng"], "second") == ""
    assert repo.record_batch(one, ["eng"], "second") == ""  # duplicate batch id ignored
    loaded = repo.load()
    assert loaded.attempted == 2 and loaded.batch_ids == ("first", "second")


def test_settings_file_format_and_lock(tmp_path: Path) -> None:
    repo = SettingsRepository(tmp_path)
    repo.save(Settings(), None)
    raw = (tmp_path / SETTINGS_FILE_NAME).read_text()
    assert raw.endswith("}\n") and raw.startswith('{\n  "deskew"')
    assert json.loads(raw) == Settings().to_json()
    assert sorted(p.name for p in tmp_path.iterdir()) == [SETTINGS_FILE_NAME]  # lock removed
    loaded = repo.load()
    assert loaded.error == "" and loaded.status is LoadStatus.LOADED
    assert str(SettingsSaveError("stale", "x")) == "stale: x"


def test_settings_load_reads_whole_file_and_backup_only_when_malformed(tmp_path: Path) -> None:
    repo = SettingsRepository(tmp_path)
    fp = repo.save(Settings(output_suffix="_" + "a" * 30), None)
    repo.save(Settings(), fp)
    assert not (tmp_path / f"{SETTINGS_FILE_NAME}.invalid.bak").exists()
    assert repo.load().settings == Settings()


def test_settings_lock_waits_then_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from searchify_pdf.storage import settings_repository as mod
    from searchify_pdf.storage.locks import FileLock

    holder = FileLock(tmp_path / f".{SETTINGS_FILE_NAME}.lock")
    holder.acquire()
    calls = []

    def fake_sleep(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) == 3:
            holder.release()

    monkeypatch.setattr(mod.time, "sleep", fake_sleep)
    SettingsRepository(tmp_path).save(Settings(), None)
    assert calls == [0.05, 0.05, 0.05]


def test_publisher_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "a_searchable.pdf"
    staging = new_staging_path(dest)
    assert staging.parent == tmp_path and staging.name.startswith(".a_searchable.pdf.")
    assert new_staging_path(dest) != staging
    good = synthetic.scanned_pdf(tmp_path / "g.pdf")
    with pytest.raises(PublishError) as info:
        validate_output(good, 2)
    assert info.value.detail == "1 pages, expected 2"
    with pytest.raises(PublishError) as info:
        validate_output(tmp_path / "missing.pdf", 1)
    assert "missing.pdf" in info.value.detail
    assert str(PublishError(Reason.LOCKED, "d")) == "locked: d"

    def boom(*_: object) -> None:
        raise OSError(5, "I/O error")

    monkeypatch.setattr(publisher.os, "link", boom)
    staging.write_bytes(b"x")
    with pytest.raises(PublishError) as info:
        publish(staging, dest, overwrite=False)
    assert info.value.reason is Reason.WRITE_FAILED and "I/O error" in info.value.detail
    assert staging.exists() and not dest.exists()


def test_discovery_walk_details(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.pdf").write_bytes(b"%PDF")
    (tmp_path / "c.pdf").symlink_to(tmp_path / "b.pdf")
    (tmp_path / "d.pdf").write_bytes(b"%PDF")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "e.pdf").write_bytes(b"%PDF")
    result = discover([tmp_path], "_searchable", ["_searchable"], lambda _: False)
    assert [c.source.name for c in result.candidates] == ["b.pdf", "d.pdf", "e.pdf"]
    assert [(o.path.name, o.reason) for o in result.omissions] == [("c.pdf", Reason.SYMLINK)]
    assert result.candidates[0].explicit is False and result.candidates[0].looks_generated is False


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_unreadable_folder_omission_has_path_and_detail(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        result = discover([tmp_path], "_searchable", ["_searchable"], lambda _: False)
    finally:
        locked.chmod(0o755)
    omission = result.omissions[0]
    assert omission.path == locked and "Permission denied" in omission.detail
    collision = discover([tmp_path / "x"], "_s", ["_s"], lambda _: False)
    assert collision.omissions[0].path == tmp_path / "x"


def test_destination_collision_detail(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    (tmp_path / "a_searchable.pdf").write_bytes(b"%PDF")
    result = discover(
        [tmp_path / "a.pdf", tmp_path / "a_searchable.pdf"],
        "_searchable",
        ["_searchable"],
        lambda _: False,
    )
    assert result.omissions[0].detail == str(tmp_path / "a_searchable.pdf")


def test_scheduler_exact_values(monkeypatch: pytest.MonkeyPatch) -> None:
    assert scheduler.auto_documents(3, 100 * scheduler.MEMORY_PER_DOCUMENT) == 1
    assert scheduler.auto_documents(4, 100 * scheduler.MEMORY_PER_DOCUMENT) == 2
    assert scheduler.auto_documents(40, 3 * scheduler.MEMORY_PER_DOCUMENT - 1) == 2
    monkeypatch.setattr(scheduler.os, "cpu_count", lambda: None)
    cpu, _ = scheduler.system_resources()
    assert cpu == 1
    plan = scheduler.plan_workers(Settings(), 1, cpu_count=8, available_memory=10**12)
    assert (plan.documents, plan.page_jobs) == (1, 8)


def test_error_details_are_propagated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from searchify_pdf.storage import settings_repository as srepo
    from searchify_pdf.storage import statistics as stmod

    def full(*_: object) -> None:
        raise OSError(28, "device full")

    monkeypatch.setattr(srepo, "atomic_write_bytes", full)
    with pytest.raises(SettingsSaveError) as info:
        SettingsRepository(tmp_path).save(Settings(), None)
    assert "device full" in info.value.detail
    monkeypatch.setattr(stmod, "atomic_write_bytes", full)
    with pytest.raises(StatisticsError) as sinfo:
        StatisticsRepository(tmp_path).save(Statistics())
    assert "device full" in str(sinfo.value)
    (tmp_path / STATS_FILE_NAME).write_text("{bad")
    with pytest.raises(StatisticsError) as sinfo:
        StatisticsRepository(tmp_path).load()
    assert "Expecting" in str(sinfo.value)
    with pytest.raises(SettingsSaveError) as info:
        SettingsRepository(tmp_path / "missing").save(Settings(), None)
    assert "No such file" in info.value.detail


def test_statistics_os_error_details(tmp_path: Path) -> None:
    (tmp_path / STATS_FILE_NAME).mkdir()
    (tmp_path / STATS_FILE_NAME / "x").write_text("keep dir non-empty")
    for action in (StatisticsRepository(tmp_path).load, StatisticsRepository(tmp_path).reset):
        with pytest.raises(StatisticsError) as info:
            action()
        assert STATS_FILE_NAME in str(info.value)


def test_settings_load_fallbacks_are_defaults(tmp_path: Path) -> None:
    from searchify_pdf.storage.settings_repository import MAX_SETTINGS_BYTES

    (tmp_path / SETTINGS_FILE_NAME).write_bytes(b" " * (MAX_SETTINGS_BYTES + 1))
    loaded = SettingsRepository(tmp_path).load()
    assert (loaded.settings, loaded.status, loaded.error) == (
        Settings(),
        LoadStatus.MALFORMED,
        "too_large",
    )
    assert loaded.fingerprint is not None
    (tmp_path / SETTINGS_FILE_NAME).write_bytes(b" " * MAX_SETTINGS_BYTES)
    assert (
        SettingsRepository(tmp_path).load().error == "json_invalid"
    )  # exactly at the limit: parsed
    (tmp_path / SETTINGS_FILE_NAME).unlink()
    (tmp_path / SETTINGS_FILE_NAME).mkdir()
    loaded = SettingsRepository(tmp_path).load()
    assert loaded.settings == Settings() and loaded.status is LoadStatus.MALFORMED


def test_settings_lock_stale_after_one_minute(tmp_path: Path) -> None:
    import socket
    import time as _time

    lock = tmp_path / f".{SETTINGS_FILE_NAME}.lock"
    lock.write_text(
        json.dumps(
            {"host": socket.gethostname() + "-other", "pid": 1, "created": _time.time() - 60.6}
        )
    )
    SettingsRepository(tmp_path).save(Settings(), None)  # stale lock broken, no 'busy'


def test_record_counts_repeated_outcomes_and_single_page_estimate() -> None:
    def result(ocr: int) -> JobResult:
        return JobResult(
            0,
            Path("x"),
            None,
            Outcome.CONVERTED,
            Reason.OK,
            "",
            3.0,
            0.0,
            PageCounts(1, ocr, 1 - ocr),
        )

    stats = record(
        Statistics(), BatchSummary((result(1), result(1)), wall_seconds=1.23456), ["eng"], "x"
    )
    assert stats.outcomes == {"converted": 2}
    assert stats.page_estimate_seconds == (3.0, 3.0)
    assert stats.to_json()["batch_wall_seconds"] == [1.2346]


def test_more_settings_bounds() -> None:
    from searchify_pdf.domain.settings import MAX_TIMEOUT_SECONDS

    assert Settings(timeout_seconds=MAX_TIMEOUT_SECONDS).timeout_seconds == MAX_TIMEOUT_SECONDS
    assert Settings(output_suffix="X.").output_suffix == "X."
    assert (
        str(SettingsSaveError("busy", "d")) == "busy: d"
        and SettingsSaveError("busy", "d").detail == "d"
    )


def test_discovery_omission_paths_and_order(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    (tmp_path / "note.txt").write_text("x")
    result = discover([tmp_path, tmp_path / "note.txt"], "_s", ["_s"], lambda _: False)
    assert [(o.path, o.reason) for o in result.omissions] == [
        (tmp_path / "link", Reason.SYMLINK),
        (tmp_path / "note.txt", Reason.NOT_PDF),
    ]
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    for p in (a, b):
        p.write_bytes(b"%PDF")
    dup = discover([a, a, b], "_s", ["_s"], lambda _: False)
    assert [c.source for c in dup.candidates] == [a, b] and dup.omissions == ()
    upper, lower = tmp_path / "Scan.pdf", tmp_path / "scan.PDF"
    upper.write_bytes(b"%PDF")
    lower.write_bytes(b"%PDF")
    if not upper.samefile(lower):
        picked = discover([lower, upper], "_s", ["_s"], lambda _: False)
        assert [c.source for c in picked.candidates] == [upper]  # deterministic: sorted by path
