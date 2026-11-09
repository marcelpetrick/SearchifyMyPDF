# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Atomic file replacement and OS-error classification."""

from __future__ import annotations

import contextlib
import errno
import os
import secrets
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` so readers see either the old or the new content.

    A temp file is written in the same directory, flushed to disk and renamed over the
    target. On any failure the temp file is removed and the previous file is untouched.
    """
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        with tmp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def classify_os_error(error: OSError) -> str:
    """Map an OSError to a reason code understood by the UI and CLI."""
    if error.errno in {errno.ENOSPC, errno.EDQUOT}:
        return "disk_full"
    if error.errno == errno.EROFS:
        return "read_only"
    if isinstance(error, PermissionError) or error.errno in {errno.EACCES, errno.EPERM}:
        return "permission_denied"
    return "write_failed"
