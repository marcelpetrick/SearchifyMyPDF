# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Packaged end-to-end tests: run the built executable in clean containers (A08-A10).

The containers contain neither Python nor Tesseract and have no network, so a pass
proves the one-file executable is self-contained and works offline. Requires
``SEARCHIFY_E2E_BINARY`` (path to the executable) and Docker; run via
``scripts/e2e_packaged.sh``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests import synthetic
from tests.textutil import all_text, contains_words, sha256

pytestmark = pytest.mark.e2e
BINARY = os.environ.get("SEARCHIFY_E2E_BINARY", "")
CLEAN_IMAGE = os.environ.get("SEARCHIFY_E2E_IMAGE", "ubuntu:22.04")
DESKTOP_IMAGE = os.environ.get("SEARCHIFY_E2E_DESKTOP_IMAGE", "searchify-pdf-e2e-desktop:local")

if not BINARY or not Path(BINARY).is_file() or shutil.which("docker") is None:
    pytest.skip("packaged binary or docker not available", allow_module_level=True)


def _app_dir(tmp_path: Path) -> Path:
    app = tmp_path / "Apps folder"
    app.mkdir()
    shutil.copy2(BINARY, app / "searchify-pdf")
    return app


def _docker(
    app: Path,
    data: Path,
    *args: str,
    image: str = CLEAN_IMAGE,
    app_ro: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{app}:/app{':ro' if app_ro else ''}",
        "-v",
        f"{data}:/data",
        "-e",
        "HOME=/tmp",
    ]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [image, "/app/searchify-pdf", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=900, check=False)


def _corpus(data: Path) -> dict[Path, str]:
    (data / "Verträge 2025" / "Kunde Ä").mkdir(parents=True)
    synthetic.scanned_pdf(
        data / "Verträge 2025" / "Kunde Ä" / "Rechnung 1.pdf", (synthetic.GERMAN_LINES,)
    )
    synthetic.scanned_pdf(data / "Invoice.PDF", (synthetic.ENGLISH_LINES, synthetic.ENGLISH_LINES))
    synthetic.mixed_pdf(data / "mixed.pdf")
    return {p: sha256(p) for p in data.rglob("*") if p.is_file()}


def test_version_and_inventory(tmp_path: Path) -> None:
    app = _app_dir(tmp_path)
    done = _docker(app, tmp_path, "--version")
    assert done.returncode == 0 and "searchify-pdf" in done.stdout
    licenses = _docker(app, tmp_path, "--licenses").stdout
    for name in ("tesseract-ocr", "Qt", "ocrmypdf", "tessdata_fast/deu.traineddata", "PySide6"):
        assert name.lower() in licenses.lower(), name


def test_offline_recursive_conversion_keeps_originals(tmp_path: Path) -> None:
    app, data = _app_dir(tmp_path), tmp_path / "data"
    data.mkdir()
    originals = _corpus(data)
    done = _docker(app, data, "--cli", "--non-interactive", "/data")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "3 converted" in done.stdout
    assert contains_words(
        all_text(data / "Verträge 2025" / "Kunde Ä" / "Rechnung 1_searchable.pdf"),
        ["Rechnung", "Vertrag"],
    )
    assert contains_words(all_text(data / "Invoice_searchable.pdf"), ["invoice", "Payment"])
    assert contains_words(all_text(data / "mixed_searchable.pdf"), ["Digital", "Searchable"])
    assert {p: sha256(p) for p in originals} == originals
    assert not (data / "output").exists()
    assert not list(data.rglob(".*"))  # no staging or lock leftovers
    again = _docker(app, data, "--cli", "--non-interactive", "/data")
    assert again.returncode == 3  # Ask (default) without a terminal never hangs
    assert not list(data.rglob("*_searchable_searchable.pdf"))


def test_portable_settings_travel_with_app(tmp_path: Path) -> None:
    app, data = _app_dir(tmp_path), tmp_path / "data"
    data.mkdir()
    synthetic.scanned_pdf(data / "a.pdf")
    (app / "searchify-pdf.settings.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "output_suffix": "_ocr",
                "existing_output_policy": "never_overwrite",
                "ocr_languages": ["eng"],
            }
        )
    )
    done = _docker(app, data, "--cli", "/data", app_ro=True)  # read-only app folder still works
    assert done.returncode == 0, done.stdout + done.stderr
    assert (data / "a_ocr.pdf").exists()
    assert sorted(p.name for p in app.iterdir()) == ["searchify-pdf", "searchify-pdf.settings.json"]
    again = _docker(app, data, "--cli", "/data", app_ro=True)
    assert again.returncode == 0 and "1 skipped" in again.stdout


def test_gui_drop_launch_offscreen(tmp_path: Path) -> None:
    app, data = _app_dir(tmp_path), tmp_path / "data"
    data.mkdir()
    synthetic.scanned_pdf(data / "dropped.pdf")
    done = _docker(
        app,
        data,
        "--gui-smoke-test",
        "/data",
        image=DESKTOP_IMAGE,
        env={"QT_QPA_PLATFORM": "offscreen"},
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "gui-smoke ok" in done.stdout
    assert contains_words(all_text(data / "dropped_searchable.pdf"), ["invoice"])
