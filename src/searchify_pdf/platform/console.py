# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Is someone at a terminal who can answer questions?

``isatty()`` alone is not enough on Windows: the ``NUL`` device is a character device,
so ``isatty()`` is True for ``< NUL`` input, scheduled tasks and CI runners. There the
handle must also be a real console (``GetConsoleMode`` succeeds).
"""

from __future__ import annotations

import ctypes
import importlib
import os
from typing import TextIO

# os.name rather than sys.platform: mypy would treat the Windows branch as unreachable.
_WINDOWS = os.name == "nt"


def is_terminal(stream: TextIO) -> bool:
    """True only for an interactive terminal (never for files, pipes or ``NUL``)."""
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError, OSError):  # closed or replaced streams
        return False
    return _is_windows_console(stream) if _WINDOWS else True


def _is_windows_console(stream: TextIO) -> bool:  # pragma: no cover - Windows runners only
    msvcrt = importlib.import_module("msvcrt")
    try:
        handle = msvcrt.get_osfhandle(stream.fileno())
    except (AttributeError, ValueError, OSError):  # e.g. an in-memory stream
        return True  # it claimed to be a terminal and has no OS handle to disprove it
    mode = ctypes.c_ulong()
    kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009 - absent from non-Windows stubs
    return bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
