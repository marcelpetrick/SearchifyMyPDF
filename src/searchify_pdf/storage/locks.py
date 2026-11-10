# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Cross-process lock files with stale-lock recovery.

Several app instances may target the same output (VISION §3.4). A lock is a file
created with ``O_CREAT | O_EXCL`` containing the owner's host, PID and creation time.
A lock owned by a process on *this* host is stale exactly when that process is gone (or
its PID was reused by a process started after the lock was written) — a live owner is
never overridden, however long its job runs. Locks from another host (network shares)
cannot be checked that way and are stale once older than ``stale_after``, which exceeds
the longest allowed job (``MAX_TIMEOUT_SECONDS``). Stale locks are broken by atomically renaming them
away first, so two instances cannot both "break" the lock and then both own it.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import socket
import time
from collections.abc import Callable
from pathlib import Path

import psutil

from searchify_pdf.domain.settings import MAX_TIMEOUT_SECONDS

DEFAULT_STALE_AFTER = MAX_TIMEOUT_SECONDS + 3600.0
PID_REUSE_TOLERANCE = 1.0  # seconds between process start and its first lock write


def process_started(pid: int) -> float | None:
    """Start time of ``pid`` (epoch seconds), or None when unknown or not permitted."""
    try:
        return float(psutil.Process(pid).create_time())
    except (psutil.Error, OSError):
        return None


def _owner_record() -> bytes:
    return json.dumps(
        {"host": socket.gethostname(), "pid": os.getpid(), "created": time.time()}
    ).encode()


class FileLock:
    """A non-blocking, exclusive lock bound to ``path``."""

    def __init__(
        self,
        path: Path,
        *,
        stale_after: float = DEFAULT_STALE_AFTER,
        pid_exists: Callable[[int], bool] = psutil.pid_exists,
        started: Callable[[int], float | None] = process_started,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.stale_after = stale_after
        self._pid_exists = pid_exists
        self._started = started
        self._clock = clock
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self) -> bool:
        """Try to take the lock; return False if another live owner holds it."""
        if self._held:
            return True
        if self._create():
            return True
        if self._is_stale() and self._break_stale():
            return self._create()
        return False

    def release(self) -> None:
        if self._held:
            self._held = False
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()

    def __enter__(self) -> FileLock:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    def _create(self) -> bool:
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        try:
            os.write(fd, _owner_record())
        finally:
            os.close(fd)
        self._held = True
        return True

    def _read(self, path: Path) -> dict[str, object] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _record_is_stale(self, record: dict[str, object] | None, path: Path) -> bool:
        if record is None:
            # Unreadable/half-written lock: stale only once it is old enough.
            try:
                age = self._clock() - path.stat().st_mtime
            except OSError:
                return True
            return age > 60
        created = record.get("created")
        pid = record.get("pid")
        if record.get("host") == socket.gethostname() and isinstance(pid, int):
            return not self._owner_alive(pid, created)
        return isinstance(created, int | float) and self._clock() - created > self.stale_after

    def _owner_alive(self, pid: int, created: object) -> bool:
        if not self._pid_exists(pid):
            return False
        started = self._started(pid)
        if started is None or not isinstance(created, int | float):
            return True
        return started <= created + PID_REUSE_TOLERANCE  # later start: PID was reused

    def _is_stale(self) -> bool:
        return self._record_is_stale(self._read(self.path), self.path)

    def _break_stale(self) -> bool:
        graveyard = self.path.with_name(f"{self.path.name}.stale-{secrets.token_hex(4)}")
        try:
            os.rename(self.path, graveyard)
        except FileNotFoundError:
            return True  # somebody else removed it; just try to create
        except OSError:
            return False
        if self._record_is_stale(self._read(graveyard), graveyard):
            with contextlib.suppress(OSError):
                graveyard.unlink()
            return True
        # We moved a fresh lock created after our check: put it back without clobbering.
        with contextlib.suppress(OSError):
            os.link(graveyard, self.path)
        with contextlib.suppress(OSError):
            graveyard.unlink()
        return False
