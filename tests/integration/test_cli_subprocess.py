# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Run the real entry point in a child process with real OCR (A01, A03, A09 headless)."""

import os
import signal
import subprocess
import sys
import time
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


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_signal_cancels_a_headless_run_cleanly(tmp_path: Path, signum: int) -> None:
    """Ctrl+C / `docker stop` cancel the batch, kill OCR and leave no partial copies."""
    folder = tmp_path / "in"
    folder.mkdir()
    for index in range(6):
        synthetic.scanned_pdf(folder / f"scan{index}.pdf", [synthetic.ENGLISH_LINES] * 4)
    env = dict(os.environ, SEARCHIFY_PDF_HOME=str(tmp_path))
    child = subprocess.Popen(
        [sys.executable, "-m", "searchify_pdf", "--cli", "--jobs", "1", str(folder)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    deadline = time.monotonic() + 60
    while not list(folder.glob("*.searchify-partial")) and time.monotonic() < deadline:
        time.sleep(0.05)  # wait until OCR is really running
    child.send_signal(signum)
    output, _ = child.communicate(timeout=60)
    assert child.returncode == 1, output
    assert "cancelling" in output and "cancelled" in output
    assert not list(folder.glob(".*searchify*")), "staging or lock files left behind"
    assert len(list(folder.glob("*_searchable.pdf"))) < 6
