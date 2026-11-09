# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
import errno
import os
from pathlib import Path

import pytest

from searchify_pdf.application.scheduler import (
    AUTO_MAX_WORKERS,
    MEMORY_PER_DOCUMENT,
    auto_documents,
    plan_workers,
    system_resources,
)
from searchify_pdf.domain.jobs import Reason
from searchify_pdf.domain.settings import Settings, WorkerMode
from searchify_pdf.storage import publisher
from searchify_pdf.storage.publisher import (
    PublishError,
    destination_problem,
    new_staging_path,
    publish,
    validate_output,
)
from tests import synthetic

GIB = 1024**3


# --- scheduler ------------------------------------------------------------------------


def test_auto_documents_bounds() -> None:
    assert auto_documents(1, 64 * GIB) == 1
    assert auto_documents(8, 64 * GIB) == 4
    assert auto_documents(64, 512 * GIB) == AUTO_MAX_WORKERS
    assert auto_documents(16, 2 * MEMORY_PER_DOCUMENT) == 2
    assert auto_documents(16, 0) == 1


def test_plan_modes_share_cpu_budget() -> None:
    auto = plan_workers(Settings(), 100, cpu_count=8, available_memory=64 * GIB)
    assert (auto.documents, auto.page_jobs, auto.mode) == (4, 2, WorkerMode.AUTO)
    seq = plan_workers(
        Settings(worker_mode=WorkerMode.SEQUENTIAL), 100, cpu_count=8, available_memory=GIB
    )
    assert (seq.documents, seq.page_jobs) == (1, 8)
    fixed = plan_workers(
        Settings(worker_mode=WorkerMode.FIXED, fixed_workers=12),
        100,
        cpu_count=8,
        available_memory=GIB,
    )
    assert (fixed.documents, fixed.page_jobs) == (12, 1)
    few = plan_workers(
        Settings(worker_mode=WorkerMode.FIXED, fixed_workers=5),
        2,
        cpu_count=8,
        available_memory=GIB,
    )
    assert (few.documents, few.page_jobs) == (2, 4)
    none = plan_workers(Settings(), 0, cpu_count=0, available_memory=0)
    assert (none.documents, none.page_jobs) == (1, 1)
    for plan in (auto, seq, few):
        assert plan.documents * plan.page_jobs <= 8


def test_system_resources() -> None:
    cpu, memory = system_resources()
    assert cpu >= 1 and memory > 0


# --- publisher ------------------------------------------------------------------------


def test_destination_problem(tmp_path: Path) -> None:
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    assert destination_problem(src, tmp_path / "a_searchable.pdf") is None
    assert destination_problem(src, tmp_path / "A.PDF") is Reason.DESTINATION_ALIAS
    link = tmp_path / "hard_searchable.pdf"
    os.link(src, link)
    assert destination_problem(src, link) is Reason.DESTINATION_ALIAS
    sym = tmp_path / "sym_searchable.pdf"
    sym.symlink_to(tmp_path / "elsewhere.pdf")
    assert destination_problem(src, sym) is Reason.DESTINATION_SYMLINK
    other = tmp_path / "b_searchable.pdf"
    other.write_bytes(b"y")
    assert destination_problem(src, other) is None


def test_destination_problem_samefile_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "d.pdf"
    dest.write_bytes(b"x")

    def boom(self: Path, other: Path) -> bool:
        raise PermissionError("no")

    monkeypatch.setattr(Path, "samefile", boom)
    assert destination_problem(tmp_path / "s.pdf", dest) is Reason.UNREADABLE


def test_validate_output(tmp_path: Path) -> None:
    good = synthetic.scanned_pdf(tmp_path / "g.pdf", (["a"], ["b"]))
    validate_output(good, 2)
    with pytest.raises(PublishError) as info:
        validate_output(good, 3)
    assert info.value.reason is Reason.VALIDATION_FAILED
    with pytest.raises(PublishError):
        validate_output(synthetic.corrupt_pdf(tmp_path / "c.pdf"), 1)
    assert "validation_failed" in str(info.value)
    assert str(PublishError(Reason.OK)) == "ok"


def _staged(dest: Path, content: bytes = b"new") -> Path:
    staging = new_staging_path(dest)
    staging.write_bytes(content)
    return staging


def test_publish_no_clobber(tmp_path: Path) -> None:
    dest = tmp_path / "a_searchable.pdf"
    staging = _staged(dest)
    publish(staging, dest, overwrite=False)
    assert dest.read_bytes() == b"new" and not staging.exists()
    second = _staged(dest, b"other")
    with pytest.raises(PublishError) as info:
        publish(second, dest, overwrite=False)
    assert info.value.reason is Reason.OUTPUT_EXISTS
    assert dest.read_bytes() == b"new"


def test_publish_overwrite(tmp_path: Path) -> None:
    dest = tmp_path / "a_searchable.pdf"
    dest.write_bytes(b"old")
    publish(_staged(dest), dest, overwrite=True)
    assert dest.read_bytes() == b"new"
    sym = tmp_path / "s_searchable.pdf"
    sym.symlink_to(dest)
    with pytest.raises(PublishError) as info:
        publish(_staged(sym), sym, overwrite=True)
    assert info.value.reason is Reason.DESTINATION_SYMLINK


def _no_links(monkeypatch: pytest.MonkeyPatch, code: int = errno.EPERM) -> None:
    def no_link(*_: object) -> None:
        raise OSError(code, "no hard links")

    monkeypatch.setattr(publisher.os, "link", no_link)


def test_publish_fallback_without_hardlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_links(monkeypatch)
    dest = tmp_path / "a_searchable.pdf"
    staging = _staged(dest)
    publish(staging, dest, overwrite=False)
    assert dest.read_bytes() == b"new" and not staging.exists()
    with pytest.raises(PublishError) as info:
        publish(_staged(dest, b"x"), dest, overwrite=False)
    assert info.value.reason is Reason.OUTPUT_EXISTS
    assert dest.read_bytes() == b"new"


def test_publish_io_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "a_searchable.pdf"
    _no_links(monkeypatch, errno.ENOSPC)
    with pytest.raises(PublishError) as info:
        publish(_staged(dest), dest, overwrite=False)
    assert info.value.reason is Reason.DISK_FULL

    def denied(*_: object) -> None:
        raise PermissionError(errno.EACCES, "denied")

    monkeypatch.setattr(publisher.os, "replace", denied)
    with pytest.raises(PublishError) as info:
        publish(_staged(dest), dest, overwrite=True)
    assert info.value.reason is Reason.PERMISSION_DENIED

    def readonly(*_: object) -> None:
        raise OSError(errno.EROFS, "ro")

    monkeypatch.setattr(publisher.os, "replace", readonly)
    with pytest.raises(PublishError) as info:
        publish(_staged(dest), dest, overwrite=True)
    assert info.value.reason is Reason.PERMISSION_DENIED
