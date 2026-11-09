# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Failure-safe publication of generated copies (VISION §4.3, ADR 0004).

1. The engine writes into a hidden *staging* file in the destination directory, so the
   final rename stays on one filesystem.
2. The staging file is validated (opens as PDF, same page count as the source).
3. Publication:

   * **overwrite** — ``os.replace``: atomic; the previous copy stays intact until the
     validated replacement is in place.
   * **no-clobber** — ``os.link(staging, destination)`` fails atomically if the
     destination appeared meanwhile. On filesystems without hard links (FAT/exFAT,
     some network shares) it falls back to "check, then rename" while holding the
     per-target lock, which serializes Searchify instances but not foreign writers.

Originals are only ever read. Destinations that are symlinks, or that resolve to the
source (hard link, case-insensitive alias), are rejected.
"""

from __future__ import annotations

import contextlib
import errno
import os
import secrets
from pathlib import Path

from searchify_pdf.domain.jobs import Reason
from searchify_pdf.domain.paths import STAGING_MARKER, staging_path_for
from searchify_pdf.engines.pdf_inspect import count_pages
from searchify_pdf.storage.atomic import classify_os_error

NO_HARDLINK_ERRNOS = {
    errno.EPERM,
    errno.EXDEV,
    errno.EMLINK,
    errno.ENOSYS,
    errno.EOPNOTSUPP,
    errno.ENOTSUP,
    errno.EACCES,
}
_REASON_BY_CODE = {
    "disk_full": Reason.DISK_FULL,
    "permission_denied": Reason.PERMISSION_DENIED,
    "read_only": Reason.PERMISSION_DENIED,
    "write_failed": Reason.WRITE_FAILED,
}


class PublishError(Exception):
    def __init__(self, reason: Reason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


def reason_for_os_error(error: OSError) -> Reason:
    return _REASON_BY_CODE[classify_os_error(error)]


def destination_problem(source: Path, destination: Path) -> Reason | None:
    """Reject destinations that alias the original or would write through a symlink."""
    if destination.is_symlink():
        return Reason.DESTINATION_SYMLINK
    if str(destination).casefold() == str(source).casefold():
        return Reason.DESTINATION_ALIAS
    if destination.exists():
        try:
            if destination.samefile(source):
                return Reason.DESTINATION_ALIAS
        except OSError:
            return Reason.UNREADABLE
    return None


def new_staging_path(destination: Path) -> Path:
    return staging_path_for(destination, secrets.token_hex(6))


def remove_stale_staging(destination: Path) -> int:
    """Delete leftover staging files of ``destination`` from an interrupted earlier run.

    Only call while holding the target's lock: then no live writer owns such a file.
    Returns the number of removed files.
    """
    removed = 0
    pattern = f".{destination.name}.*{STAGING_MARKER}"
    for leftover in destination.parent.glob(pattern):
        with contextlib.suppress(OSError):
            leftover.unlink()
            removed += 1
    return removed


def discard(staging: Path) -> None:
    with contextlib.suppress(OSError):
        staging.unlink()


def validate_output(staging: Path, expected_pages: int) -> None:
    try:
        pages = count_pages(staging)
    except Exception as exc:  # any parser failure means the output is unusable
        raise PublishError(Reason.VALIDATION_FAILED, str(exc)) from exc
    if pages != expected_pages:
        raise PublishError(Reason.VALIDATION_FAILED, f"{pages} pages, expected {expected_pages}")


def publish(staging: Path, destination: Path, *, overwrite: bool) -> None:
    """Move a validated staging file into place; raise :class:`PublishError` on failure."""
    try:
        if overwrite:
            if destination.is_symlink():
                raise PublishError(Reason.DESTINATION_SYMLINK)
            os.replace(staging, destination)
            return
        try:
            os.link(staging, destination)
        except FileExistsError as exc:
            raise PublishError(Reason.OUTPUT_EXISTS) from exc
        except OSError as exc:
            if exc.errno not in NO_HARDLINK_ERRNOS:
                raise
            if destination.exists() or destination.is_symlink():
                raise PublishError(Reason.OUTPUT_EXISTS) from exc
            os.rename(staging, destination)
            return
        discard(staging)
    except PublishError:
        raise
    except OSError as exc:
        raise PublishError(reason_for_os_error(exc), str(exc)) from exc
