# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Run the real entry point in a child process with real OCR (A01, A03, A09 headless)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import synthetic
from tests.textutil import all_text, contains_words

pytestmark = pytest.mark.ocr


def test_python_m_searchify_pdf_cli(tmp_path: Path) -> None:
    (tmp_path / "in" / "nested dir").mkdir(parents=True)
    synthetic.scanned_pdf(tmp_path / "in" / "nested dir" / "scan.pdf")
    env = dict(os.environ, SEARCHIFY_PDF_HOME=str(tmp_path))
    env.pop("QT_QPA_PLATFORM", None)
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    done = subprocess.run(
        [sys.executable, "-m", "searchify_pdf", str(tmp_path / "in")],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 converted" in done.stdout
    out = tmp_path / "in" / "nested dir" / "scan_searchable.pdf"
    assert contains_words(all_text(out), ["Searchable", "invoice"])
    again = subprocess.run(
        [sys.executable, "-m", "searchify_pdf", "--cli", str(tmp_path / "in")],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,
    )
    assert again.returncode == 3  # Ask policy, no terminal: needs a decision, never hangs
