# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Fault and adversarial scenarios with the real engine (A02, A12, A14, A20)."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from searchify_pdf.domain.jobs import Reason
from searchify_pdf.engines.base import EngineRequest, OcrMode
from searchify_pdf.engines.ocrmypdf_engine import OcrmypdfEngine
from tests import synthetic
from tests.textutil import all_text, contains_words, sha256

pytestmark = pytest.mark.ocr


def _cli(*args: str, home: Path) -> subprocess.Popen[str]:
    env = dict(os.environ, SEARCHIFY_PDF_HOME=str(home))
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"):
        env.pop(key, None)
    return subprocess.Popen(
        [sys.executable, "-m", "searchify_pdf", "--cli", "--non-interactive", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        start_new_session=True,
    )


def test_simultaneous_instances_never_race_on_one_output(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    for i in range(3):
        synthetic.scanned_pdf(data / f"doc{i}.pdf", [synthetic.ENGLISH_LINES] * 2)
    originals = {p: sha256(p) for p in data.iterdir()}
    procs = [_cli("--on-existing-output", "overwrite", str(data), home=tmp_path) for _ in range(3)]
    outputs = [p.communicate(timeout=600)[0] for p in procs]
    assert all(p.returncode == 0 for p in procs), outputs
    for i in range(3):
        assert contains_words(all_text(data / f"doc{i}_searchable.pdf"), ["invoice"])
    assert {p: sha256(p) for p in originals} == originals
    assert sorted(p.name for p in data.iterdir() if p.name.startswith(".")) == []


def test_hard_kill_during_ocr_then_recovery(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    src = synthetic.scanned_pdf(data / "big.pdf", [synthetic.ENGLISH_LINES] * 6, dpi=300)
    before = sha256(src)
    proc = _cli(str(data), home=tmp_path)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not any(
        p.name.endswith(".searchify-partial") or ".searchify-lock" in p.name for p in data.iterdir()
    ):
        time.sleep(0.05)
    time.sleep(0.5)
    children = psutil.Process(proc.pid).children(recursive=True)
    os.killpg(proc.pid, signal.SIGKILL)  # power-cut style interruption: no cleanup runs
    proc.wait(30)
    for child in children:
        with contextlib.suppress(psutil.NoSuchProcess):
            child.wait(10)
    assert sha256(src) == before
    assert not (data / "big_searchable.pdf").exists()  # never a half-written copy
    rerun = _cli("--on-existing-output", "overwrite", str(data), home=tmp_path)
    out = rerun.communicate(timeout=600)[0]
    assert rerun.returncode == 0, out
    assert contains_words(all_text(data / "big_searchable.pdf"), ["invoice"])
    assert sorted(p.name for p in data.iterdir()) == [
        "big.pdf",
        "big_searchable.pdf",
    ]  # leftovers recovered


def test_engine_timeout_kills_tesseract(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "large.pdf", [synthetic.ENGLISH_LINES] * 8, dpi=300)
    before = {p.pid for p in psutil.Process().children(recursive=True)}
    request = EngineRequest(
        src, tmp_path / "out.pdf", ("eng",), OcrMode.PRESERVE_TEXT, timeout_seconds=1.0
    )
    result = OcrmypdfEngine().run(request, threading.Event())
    assert not result.ok and result.reason is Reason.TIMEOUT
    time.sleep(0.3)
    leftover = [
        p
        for p in psutil.Process().children(recursive=True)
        if p.pid not in before and p.status() != psutil.STATUS_ZOMBIE
    ]
    assert leftover == []


def test_unusually_large_page(tmp_path: Path) -> None:
    from PIL import Image

    big = tmp_path / "poster.pdf"
    image = Image.new("L", (6000, 8500), 255)
    image.save(big, "PDF", resolution=100)
    request = EngineRequest(
        big, tmp_path / "out.pdf", ("eng",), OcrMode.PRESERVE_TEXT, timeout_seconds=300
    )
    result = OcrmypdfEngine().run(request, threading.Event())
    assert result.ok or result.reason in {Reason.ENGINE_FAILED, Reason.INVALID_PDF}


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (["--jobs", "-1", "x"], 2),
        (["--languages", "EN", "x"], 2),
        (["--suffix", "../evil", "x"], 2),
        (["--no-such-option"], 2),
        (["\x01weird\nname.pdf"], 0),
    ],
)
def test_malformed_launch_arguments(tmp_path: Path, args: list[str], code: int) -> None:
    proc = _cli(*args, home=tmp_path)
    proc.communicate(timeout=120)
    assert proc.returncode == code
