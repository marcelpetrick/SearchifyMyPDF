# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Shared pytest configuration.

The pipeline exports ``TESSDATA_PREFIX`` pointing at the pinned language data. When it
is not set we fall back to ``.cache/tessdata`` if present, so plain ``pytest`` works too.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCAL_TESSDATA = ROOT / ".cache" / "tessdata"
if "TESSDATA_PREFIX" not in os.environ and (LOCAL_TESSDATA / "eng.traineddata").exists():
    os.environ["TESSDATA_PREFIX"] = str(LOCAL_TESSDATA)


@pytest.fixture(autouse=True)
def _isolated_app_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Never write settings/statistics into the developer's real application folder."""
    home = tmp_path_factory.mktemp("apphome")
    monkeypatch.setenv("SEARCHIFY_PDF_HOME", str(home))
    return home
