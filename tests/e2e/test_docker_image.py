# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""End-to-end tests of the published CLI Docker image (offline, unprivileged).

Requires ``SEARCHIFY_E2E_DOCKER_IMAGE`` (e.g. ``searchify-pdf:local``); run via
``scripts/docker_smoke.sh``, which builds the image first.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from tests import realcorpus, synthetic
from tests.textutil import all_text, contains_words, sha256

pytestmark = pytest.mark.e2e
IMAGE = os.environ.get("SEARCHIFY_E2E_DOCKER_IMAGE", "")

if not IMAGE or shutil.which("docker") is None:
    pytest.skip("docker image not given or docker not available", allow_module_level=True)


def _writable(*dirs: Path) -> None:
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
        for path in [directory, *directory.rglob("*")]:
            path.chmod(0o777 if path.is_dir() else 0o666)  # image user is uid 1000


def _run(data: Path, *args: str, config: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "run", "--rm", "--network", "none", "-v", f"{data}:/data"]
    if config is not None:
        cmd += ["-v", f"{config}:/config"]
    return subprocess.run(
        [*cmd, IMAGE, *args], capture_output=True, text=True, timeout=900, check=False
    )


def test_image_runs_unprivileged_and_reports_version() -> None:
    who = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "id", IMAGE, "-u"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert who.stdout.strip() != "0"
    assert "searchify-pdf" in _run(Path("/tmp"), "--version").stdout


def test_image_real_life_corpus(tmp_path: Path) -> None:
    data = tmp_path / "data"
    docs = realcorpus.copy_corpus(data)
    _writable(data)
    originals = {p: sha256(p) for p in data.iterdir()}
    done = _run(data, "/data")
    assert done.returncode == 1, done.stdout + done.stderr  # the protected one fails
    for doc in docs:
        copy = data / doc.copy_name
        if doc.protected:
            assert not copy.exists()
        elif not doc.text_layer:
            assert contains_words(all_text(copy), doc.words), (doc.file, all_text(copy)[:300])
    assert "4 converted · 1 copied" in done.stdout
    assert {p: sha256(p) for p in originals} == originals
    assert not list(data.glob(".*"))


def test_image_reads_settings_from_config(tmp_path: Path) -> None:
    data, config = tmp_path / "data", tmp_path / "config"
    data.mkdir()
    config.mkdir()
    synthetic.scanned_pdf(data / "a.pdf")
    (config / "searchify-pdf.settings.json").write_text(
        json.dumps({"schema_version": 2, "output_suffix": "_ocr", "ocr_languages": ["eng"]})
    )
    _writable(data, config)
    done = _run(data, "/data", config=config)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (data / "a_ocr.pdf").exists() and not (data / "a_searchable.pdf").exists()
    again = _run(data, "--on-existing-output", "skip", "/data", config=config)
    assert again.returncode == 0 and "1 skipped" in again.stdout


def test_image_docker_stop_cancels_cleanly(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    for index in range(6):
        synthetic.scanned_pdf(data / f"scan{index}.pdf", [synthetic.ENGLISH_LINES] * 6, dpi=300)
    _writable(data)
    originals = {p: sha256(p) for p in data.iterdir()}
    name = f"searchify-image-e2e-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            *("docker", "run", "-d", "--name", name, "--network", "none"),
            *("-v", f"{data}:/data", IMAGE, "--jobs", "1", "/data"),
        ],
        check=True,
        capture_output=True,
    )
    try:
        deadline = time.monotonic() + 120
        while not list(data.glob(".*.searchify-partial")) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert list(data.glob(".*.searchify-partial")), "OCR never started"
        subprocess.run(["docker", "stop", "-t", "30", name], check=True, capture_output=True)
        code = subprocess.run(
            ["docker", "wait", name], check=True, capture_output=True, text=True
        ).stdout.strip()
        logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True).stdout
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    assert code == "1", logs
    assert "SIGTERM: cancelling" in logs
    assert not list(data.glob(".*")), "staging or lock files left behind"
    assert {p: sha256(p) for p in originals} == originals
