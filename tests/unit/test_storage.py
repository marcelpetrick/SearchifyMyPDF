# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
import errno
import json
import os
import socket
import sys
import time
from pathlib import Path

import pytest

from searchify_pdf.domain.settings import Settings, Theme
from searchify_pdf.platform import app_location
from searchify_pdf.storage import atomic
from searchify_pdf.storage.atomic import atomic_write_bytes, classify_os_error
from searchify_pdf.storage.locks import FileLock
from searchify_pdf.storage.settings_repository import (
    MAX_SETTINGS_BYTES,
    SETTINGS_FILE_NAME,
    LoadStatus,
    SettingsRepository,
    SettingsSaveError,
)

# --- atomic -------------------------------------------------------------------------


def test_atomic_write_replaces(tmp_path: Path) -> None:
    target = tmp_path / "f.json"
    target.write_bytes(b"old")
    atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["f.json"]


def test_atomic_write_failure_keeps_old(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "f.json"
    target.write_bytes(b"old")

    def boom(*_: object) -> None:
        raise OSError(errno.ENOSPC, "full")

    monkeypatch.setattr(atomic.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["f.json"]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (OSError(errno.ENOSPC, "x"), "disk_full"),
        (OSError(errno.EDQUOT, "x"), "disk_full"),
        (OSError(errno.EROFS, "x"), "read_only"),
        (PermissionError(errno.EACCES, "x"), "permission_denied"),
        (OSError(errno.EPERM, "x"), "permission_denied"),
        (OSError(errno.EIO, "x"), "write_failed"),
    ],
)
def test_classify(error: OSError, code: str) -> None:
    assert classify_os_error(error) == code


# --- locks --------------------------------------------------------------------------


def test_lock_exclusive_and_release(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    first = FileLock(path)
    assert first.acquire() and first.held
    assert first.acquire()  # re-entrant for the holder
    second = FileLock(path)
    assert not second.acquire()
    first.release()
    first.release()  # idempotent
    with second:
        assert second.acquire()
    assert not path.exists()


def _write_lock(path: Path, **record: object) -> None:
    base: dict[str, object] = {
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "created": time.time(),
    }
    base.update(record)
    path.write_text(json.dumps(base))


def test_stale_lock_dead_pid_is_broken(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    _write_lock(path, pid=999999)
    lock = FileLock(path, pid_exists=lambda pid: False)
    assert lock.acquire()
    assert json.loads(path.read_text())["pid"] == os.getpid()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.lock"]


def test_stale_lock_old_age_is_broken(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    _write_lock(path, created=time.time() - 10_000, host="elsewhere")
    assert FileLock(path, stale_after=100).acquire()


def test_live_same_host_owner_is_never_overridden_by_age(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    created = time.time() - 30 * 3600  # a very long job of a live owner
    _write_lock(path, created=created)
    assert not FileLock(path, stale_after=100, started=lambda pid: created - 10).acquire()


def test_reused_pid_makes_a_same_host_lock_stale(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    created = time.time() - 50
    _write_lock(path, created=created)
    assert not FileLock(path, started=lambda pid: created + 0.5).acquire()  # same process
    assert not FileLock(path, started=lambda pid: None).acquire()  # start time unknown
    assert FileLock(path, started=lambda pid: created + 5).acquire()  # PID reused later


def test_same_host_lock_without_creation_time_follows_the_pid(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    _write_lock(path, created="?")
    assert not FileLock(path, stale_after=0).acquire()
    assert FileLock(path, pid_exists=lambda pid: False).acquire()


def test_process_started_and_default_threshold() -> None:
    from searchify_pdf.domain.settings import MAX_TIMEOUT_SECONDS
    from searchify_pdf.storage import locks

    own = locks.process_started(os.getpid())
    assert own is not None and own <= time.time()
    assert locks.process_started(2**22 + 12345) is None
    assert locks.DEFAULT_STALE_AFTER > MAX_TIMEOUT_SECONDS


def test_live_lock_from_other_host_is_respected(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    _write_lock(path, host="elsewhere", pid=1)
    assert not FileLock(path, pid_exists=lambda pid: False).acquire()


def test_garbage_lock_depends_on_age(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    path.write_text("not json")
    assert not FileLock(path).acquire()
    old = time.time() - 120
    os.utime(path, (old, old))
    assert FileLock(path).acquire()
    path.unlink()
    path.write_text("[1]")
    os.utime(path, (old, old))
    assert FileLock(path).acquire()


def test_stale_check_tolerates_vanishing_file(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / "gone.lock")
    assert lock._record_is_stale(None, tmp_path / "gone.lock")


def test_break_stale_races(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "x.lock"
    lock = FileLock(path, pid_exists=lambda pid: False)
    # lock disappeared before rename → treat as broken
    assert lock._break_stale()
    # rename fails for another reason → give up
    _write_lock(path, pid=999999)
    real_rename = os.rename

    def fail(*_: object) -> None:
        raise PermissionError("nope")

    monkeypatch.setattr(os, "rename", fail)
    assert not lock._break_stale()
    monkeypatch.setattr(os, "rename", real_rename)


def test_break_stale_restores_fresh_lock(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    _write_lock(path)  # live owner (this process)
    lock = FileLock(path)
    assert not lock._break_stale()
    assert path.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.lock"]


# --- settings repository ------------------------------------------------------------


def test_load_defaults_when_missing(tmp_path: Path) -> None:
    result = SettingsRepository(tmp_path).load()
    assert result.status is LoadStatus.DEFAULTS
    assert result.settings == Settings()
    assert result.fingerprint is None


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    repo = SettingsRepository(tmp_path)
    fp = repo.save(Settings(theme=Theme.DARK), None)
    loaded = repo.load()
    assert loaded.status is LoadStatus.LOADED
    assert loaded.settings.theme is Theme.DARK
    assert loaded.fingerprint == fp
    data = json.loads((tmp_path / SETTINGS_FILE_NAME).read_text())
    assert data["theme"] == "dark"
    repo.save(Settings(), fp)


def test_stale_save_refused(tmp_path: Path) -> None:
    repo = SettingsRepository(tmp_path)
    fp = repo.save(Settings(), None)
    SettingsRepository(tmp_path).save(Settings(theme=Theme.LIGHT), fp)
    with pytest.raises(SettingsSaveError) as info:
        repo.save(Settings(theme=Theme.DARK), fp)
    assert info.value.code == "stale"
    assert repo.load().settings.theme is Theme.LIGHT


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (b"{not json", "json_invalid"),
        (b"\xff\xfe", "json_invalid"),
        (b'{"theme": "neon"}', "choice_invalid"),
        (b"[]", "document_invalid"),
    ],
)
def test_malformed_file_recovers_with_backup(tmp_path: Path, content: bytes, error: str) -> None:
    (tmp_path / SETTINGS_FILE_NAME).write_bytes(content)
    repo = SettingsRepository(tmp_path)
    loaded = repo.load()
    assert loaded.status is LoadStatus.MALFORMED
    assert loaded.error == error
    assert loaded.settings == Settings()
    repo.save(Settings(), loaded.fingerprint)
    assert (tmp_path / f"{SETTINGS_FILE_NAME}.invalid.bak").read_bytes() == content
    assert repo.load().status is LoadStatus.LOADED


def test_oversized_file_is_malformed(tmp_path: Path) -> None:
    (tmp_path / SETTINGS_FILE_NAME).write_bytes(b" " * (MAX_SETTINGS_BYTES + 5))
    assert SettingsRepository(tmp_path).load().error == "too_large"


def test_unreadable_file(tmp_path: Path) -> None:
    (tmp_path / SETTINGS_FILE_NAME).mkdir()
    loaded = SettingsRepository(tmp_path).load()
    assert loaded.status is LoadStatus.MALFORMED
    assert loaded.error in {"write_failed", "permission_denied"}


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_read_only_directory(tmp_path: Path) -> None:
    repo = SettingsRepository(tmp_path)
    fp = repo.save(Settings(), None)
    tmp_path.chmod(0o555)
    try:
        assert not repo.is_writable()
        with pytest.raises(SettingsSaveError) as info:
            repo.save(Settings(theme=Theme.DARK), fp)
        assert info.value.code == "permission_denied"
        assert repo.load().settings == Settings()
    finally:
        tmp_path.chmod(0o755)
    assert repo.is_writable()


def test_save_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    holder = FileLock(tmp_path / f".{SETTINGS_FILE_NAME}.lock")
    assert holder.acquire()
    with pytest.raises(SettingsSaveError) as info:
        SettingsRepository(tmp_path).save(Settings(), None)
    assert info.value.code == "busy"
    assert str(info.value) == "busy"


def test_save_write_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import searchify_pdf.storage.settings_repository as mod

    def full(*_: object) -> None:
        raise OSError(errno.ENOSPC, "full")

    monkeypatch.setattr(mod, "atomic_write_bytes", full)
    with pytest.raises(SettingsSaveError) as info:
        SettingsRepository(tmp_path).save(Settings(), None)
    assert info.value.code == "disk_full"


def test_save_lock_os_error(tmp_path: Path) -> None:
    repo = SettingsRepository(tmp_path / "missing")
    with pytest.raises(SettingsSaveError) as info:
        repo.save(Settings(), None)
    assert info.value.code == "write_failed"


# --- application location -----------------------------------------------------------


def test_location_override(tmp_path: Path) -> None:
    env = {"SEARCHIFY_PDF_HOME": str(tmp_path), "APPIMAGE": "/x/y.AppImage"}
    assert (
        app_location.application_directory(env=env, frozen=True, executable="/e", argv0="/a")
        == tmp_path
    )


def test_location_appimage(tmp_path: Path) -> None:
    env = {"APPIMAGE": str(tmp_path / "Searchify.AppImage")}
    got = app_location.application_directory(
        env=env, frozen=True, executable="/tmp/.mount/x", argv0=""
    )
    assert got == tmp_path


def test_location_frozen_and_macos_bundle(tmp_path: Path) -> None:
    exe = tmp_path / "searchify-pdf"
    assert (
        app_location.application_directory(env={}, frozen=True, executable=str(exe), argv0="")
        == tmp_path
    )
    mac = tmp_path / "Searchify PDF.app" / "Contents" / "MacOS" / "searchify-pdf"
    assert (
        app_location.application_directory(env={}, frozen=True, executable=str(mac), argv0="")
        == tmp_path
    )


def test_location_source_resolves_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "launcher").write_text("")
    (tmp_path / "shortcut").symlink_to(real / "launcher")
    got = app_location.application_directory(
        env={}, frozen=False, executable=sys.executable, argv0=str(tmp_path / "shortcut")
    )
    assert got == real


def test_current_location(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SEARCHIFY_PDF_HOME", str(tmp_path))
    assert app_location.current_application_directory() == tmp_path
    monkeypatch.delenv("SEARCHIFY_PDF_HOME")
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "argv", [""])
    assert app_location.current_application_directory() == Path(sys.executable).resolve().parent
