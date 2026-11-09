# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Portable settings file beside the application (VISION §6.1/§6.2).

* Missing file → documented defaults.
* Malformed file → defaults plus a visible ``malformed`` status; the broken file is kept
  as ``*.invalid.bak`` on the next successful save, never silently discarded.
* Save is validated and atomic; failure leaves the previous file intact.
* A fingerprint taken at load time detects concurrent edits (stale saves are refused).
* There is deliberately no fallback to a user-profile location.
"""

from __future__ import annotations

import contextlib
import dataclasses
import enum
import hashlib
import json
import os
import time
from pathlib import Path

from searchify_pdf.domain.settings import Settings, SettingsError, from_json
from searchify_pdf.storage.atomic import atomic_write_bytes, classify_os_error
from searchify_pdf.storage.locks import FileLock

SETTINGS_FILE_NAME = "searchify-pdf.settings.json"
MAX_SETTINGS_BYTES = 256 * 1024


class LoadStatus(enum.StrEnum):
    DEFAULTS = "defaults"  # no file yet
    LOADED = "loaded"
    MALFORMED = "malformed"  # file exists but could not be used; defaults in effect


@dataclasses.dataclass(frozen=True, slots=True)
class LoadResult:
    settings: Settings
    status: LoadStatus
    fingerprint: str | None
    error: str = ""


class SettingsSaveError(Exception):
    """Saving failed; ``code`` is ``read_only``, ``permission_denied``, ``disk_full``,
    ``write_failed``, ``stale`` or ``busy``."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _fingerprint(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


class SettingsRepository:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / SETTINGS_FILE_NAME

    def _read_bytes(self) -> bytes | None:
        try:
            with self.path.open("rb") as handle:
                return handle.read(MAX_SETTINGS_BYTES + 1)
        except FileNotFoundError:
            return None

    def load(self) -> LoadResult:
        try:
            raw = self._read_bytes()
        except OSError as exc:
            return LoadResult(Settings(), LoadStatus.MALFORMED, None, classify_os_error(exc))
        if raw is None:
            return LoadResult(Settings(), LoadStatus.DEFAULTS, None)
        fingerprint = _fingerprint(raw)
        if len(raw) > MAX_SETTINGS_BYTES:
            return LoadResult(Settings(), LoadStatus.MALFORMED, fingerprint, "too_large")
        try:
            settings = from_json(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return LoadResult(Settings(), LoadStatus.MALFORMED, fingerprint, "json_invalid")
        except SettingsError as exc:
            return LoadResult(Settings(), LoadStatus.MALFORMED, fingerprint, exc.code)
        return LoadResult(settings, LoadStatus.LOADED, fingerprint)

    def is_writable(self) -> bool:
        """Best-effort check whether settings can be saved beside the application."""
        return os.access(self.directory, os.W_OK | os.X_OK)

    def save(self, settings: Settings, expected_fingerprint: str | None) -> str:
        """Atomically write ``settings``; return the new fingerprint.

        ``expected_fingerprint`` is the value from :meth:`load` (or the last save). If the
        file changed meanwhile, :class:`SettingsSaveError` with code ``stale`` is raised.
        """
        payload = (json.dumps(settings.to_json(), indent=2, sort_keys=True) + "\n").encode()
        lock = FileLock(self.directory / f".{SETTINGS_FILE_NAME}.lock", stale_after=60)
        try:
            acquired = self._acquire(lock)
        except OSError as exc:
            raise SettingsSaveError(classify_os_error(exc), str(exc)) from exc
        if not acquired:
            raise SettingsSaveError("busy")
        try:
            current = self._read_bytes()
            if _fingerprint(current) != expected_fingerprint:
                raise SettingsSaveError("stale")
            if current is not None and self._is_malformed(current):
                backup = self.path.with_name(f"{SETTINGS_FILE_NAME}.invalid.bak")
                atomic_write_bytes(backup, current)
            atomic_write_bytes(self.path, payload)
        except OSError as exc:
            raise SettingsSaveError(classify_os_error(exc), str(exc)) from exc
        finally:
            lock.release()
        return _fingerprint(payload) or ""

    @staticmethod
    def _acquire(lock: FileLock, attempts: int = 20) -> bool:
        for _ in range(attempts):
            if lock.acquire():
                return True
            time.sleep(0.05)
        return False

    @staticmethod
    def _is_malformed(raw: bytes) -> bool:
        with contextlib.suppress(UnicodeDecodeError, ValueError, SettingsError):
            from_json(json.loads(raw.decode("utf-8")))
            return False
        return True
