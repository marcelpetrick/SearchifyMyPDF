# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""macOS layer of the parser sandbox (#13, ADR 0016): a Seatbelt profile.

``sandbox_init`` applies an SBPL profile to the calling process; it can't be lifted and
every child (Tesseract) inherits it. The profile allows everything by default and then
denies:

* **writes** everywhere except the writable folders and files;
* **reading file contents** in the places user data lives (``/Users``, ``/Volumes``,
  ``/Network``, the temporary folders), except the runtime folders and files the caller
  names. Metadata stays readable so path lookups keep working;
* **IP networking** (inbound, outbound, bind); local Unix sockets keep working.

Later SBPL rules take precedence over earlier ones, so the allowances follow the denials.
"""

from __future__ import annotations

import ctypes
from collections.abc import Iterable
from pathlib import Path

USER_DATA = ("/Users", "/Volumes", "/Network", "/private/tmp", "/private/var/folders")


def _quote(path: Path) -> str:
    text = str(path.resolve())
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _filters(kind: str, paths: Iterable[Path]) -> str:
    return " ".join(f"({kind} {_quote(p)})" for p in paths)


def profile(
    writable_dirs: Iterable[Path],
    writable_files: Iterable[Path],
    readable_dirs: Iterable[Path] | None,
    readable_files: Iterable[Path],
) -> str:
    """The SBPL profile; ``readable_dirs=None`` leaves reading unrestricted."""
    dirs, files = list(writable_dirs), list(writable_files)
    rules = [
        "(version 1)",
        "(allow default)",
        "(deny network-outbound (remote ip))",
        "(deny network-inbound (local ip))",
        "(deny network-bind (local ip))",
        "(deny file-write*)",
    ]
    grants = " ".join(
        part for part in (_filters("subpath", dirs), _filters("literal", files)) if part
    )
    if grants:
        rules.append(f"(allow file-write* {grants})")
    if readable_dirs is not None:
        rules.append(f"(deny file-read-data {_filters('subpath', map(Path, USER_DATA))})")
        readable = " ".join(
            part
            for part in (
                _filters("subpath", [*dirs, *readable_dirs]),
                _filters("literal", [*files, *readable_files]),
            )
            if part
        )
        if readable:
            rules.append(f"(allow file-read-data {readable})")
    return "\n".join(rules) + "\n"


def apply(text: str) -> bool:  # pragma: no cover - exercised on the macOS runner only
    """Apply ``text`` to this process; False when the system refuses it."""
    library = ctypes.CDLL(None)
    sandbox_init = library.sandbox_init
    sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
    sandbox_init.restype = ctypes.c_int
    error = ctypes.c_char_p()
    if sandbox_init(text.encode(), 0, ctypes.byref(error)) == 0:
        return True
    if error.value is not None:
        library.sandbox_free_error(error)
    return False
