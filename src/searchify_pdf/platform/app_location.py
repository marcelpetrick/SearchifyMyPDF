# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Locate the real application directory for portable settings (VISION §6.1).

Never the current working directory, a shortcut's directory, or PyInstaller's
temporary extraction directory (``sys._MEIPASS``).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

HOME_OVERRIDE = "SEARCHIFY_PDF_HOME"


def application_directory(
    *,
    env: Mapping[str, str],
    frozen: bool,
    executable: str,
    argv0: str,
) -> Path:
    """Return the folder where settings/statistics files live.

    Order: explicit ``SEARCHIFY_PDF_HOME`` override → AppImage file location →
    frozen executable location (beside a macOS ``.app`` bundle, not inside it) →
    the resolved launcher script location for source installs.
    """
    override = env.get(HOME_OVERRIDE)
    if override:
        return Path(override).expanduser().resolve()
    appimage = env.get("APPIMAGE")
    if appimage:
        return Path(appimage).resolve().parent
    if frozen:
        exe = Path(executable).resolve()
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent.parent
        return exe.parent
    return Path(argv0).resolve().parent


def current_application_directory() -> Path:
    """:func:`application_directory` for the running process."""
    return application_directory(
        env=os.environ,
        frozen=bool(getattr(sys, "frozen", False)),
        executable=sys.executable,
        argv0=sys.argv[0] if sys.argv and sys.argv[0] else sys.executable,
    )
