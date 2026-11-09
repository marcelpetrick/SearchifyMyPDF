# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Runtime environment for the bundled (frozen) application.

The PyInstaller build ships Tesseract in ``<bundle>/bin`` and the language data in
``<bundle>/tessdata``. At startup those are put first on ``PATH`` and into
``TESSDATA_PREFIX`` so no system installation is needed (VISION §10). External helper
programs such as ``xdg-open`` must not inherit the bundle's library path, so
:func:`external_env` restores the original ``LD_LIBRARY_PATH``.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path


def configure_bundled_runtime(env: MutableMapping[str, str], bundle_dir: Path | None) -> bool:
    """Point engine lookups at the bundle; return True when a bundle was configured."""
    if bundle_dir is None:
        return False
    bin_dir = bundle_dir / "bin"
    tessdata = bundle_dir / "tessdata"
    if not (bin_dir / "tesseract").exists() and not (bin_dir / "tesseract.exe").exists():
        return False
    env["PATH"] = os.pathsep.join([str(bin_dir), env.get("PATH", "")]).rstrip(os.pathsep)
    if tessdata.is_dir():
        env["TESSDATA_PREFIX"] = str(tessdata)
    return True


def external_env(env: MutableMapping[str, str]) -> dict[str, str]:
    """Environment for launching *system* programs from the frozen app."""
    result = dict(env)
    original = result.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is not None:
        result["LD_LIBRARY_PATH"] = original
    elif "_MEIPASS2" in result or "_PYI_APPLICATION_HOME_DIR" in result:
        result.pop("LD_LIBRARY_PATH", None)
    return result
