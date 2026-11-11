# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Terminal detection: files, pipes and the null device never count as a terminal."""

from __future__ import annotations

import io
import os

from searchify_pdf.platform.console import is_terminal


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


class _Broken(io.StringIO):
    def isatty(self) -> bool:
        raise ValueError("I/O operation on closed file")


def test_in_memory_streams() -> None:
    assert not is_terminal(io.StringIO())
    assert is_terminal(_Tty())  # claims a terminal, no OS handle to disprove it
    assert not is_terminal(_Broken())


def test_null_device_is_not_a_terminal() -> None:
    """On Windows ``NUL`` reports isatty() True; it must still not count as a terminal."""
    with open(os.devnull, encoding="utf-8") as null:
        assert not is_terminal(null)
