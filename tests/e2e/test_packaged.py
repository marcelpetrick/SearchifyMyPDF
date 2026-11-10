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
import time
import uuid
from pathlib import Path

import pytest

from tests import realcorpus, synthetic
from tests.textutil import all_text, contains_words, sha256

pytestmark = pytest.mark.e2e
BINARY = os.environ.get("SEARCHIFY_E2E_BINARY", "")
CLEAN_IMAGE = os.environ.get("SEARCHIFY_E2E_IMAGE", "ubuntu:22.04")
DESKTOP_IMAGE = os.environ.get("SEARCHIFY_E2E_DESKTOP_IMAGE", "searchify-pdf-e2e-desktop:local")
X11_IMAGE = os.environ.get("SEARCHIFY_E2E_X11_IMAGE", "searchify-pdf-e2e-x11:local")

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
    stdin: str | None = None,
    entry: tuple[str, ...] = ("/app/searchify-pdf",),
) -> subprocess.CompletedProcess[str]:
    cmd = _docker_cmd(app, data, image=image, app_ro=app_ro, env=env, interactive=stdin is not None)
    cmd += [image, *entry, *args]
    return subprocess.run(
        cmd, input=stdin, capture_output=True, text=True, timeout=900, check=False
    )


def _docker_cmd(
    app: Path,
    data: Path,
    *,
    image: str = CLEAN_IMAGE,
    app_ro: bool = False,
    env: dict[str, str] | None = None,
    interactive: bool = False,
    detached_name: str = "",
) -> list[str]:
    cmd = [
        "docker",
        "run",
        *(["-d", "--name", detached_name] if detached_name else ["--rm"]),
        *(["-i"] if interactive else []),
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
    return cmd


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


def test_real_life_corpus_offline(tmp_path: Path) -> None:
    """Public-domain / CC scans (1929-1967, EN + DE): text found, protection respected."""
    app, data = _app_dir(tmp_path), tmp_path / "data"
    docs = realcorpus.copy_corpus(data)
    originals = {p: sha256(p) for p in data.iterdir()}
    done = _docker(app, data, "--cli", "--non-interactive", "/data")
    assert done.returncode == 1, done.stdout + done.stderr  # the protected one fails
    for doc in docs:
        copy = data / doc.copy_name
        if doc.protected:
            assert not copy.exists()
        elif doc.text_layer:
            assert copy.exists()  # kept as is ("keep existing text")
        else:
            assert contains_words(all_text(copy), doc.words), (doc.file, all_text(copy)[:300])
    assert "4 converted · 1 copied" in done.stdout
    assert {p: sha256(p) for p in originals} == originals
    assert not list(data.glob(".*"))


def test_docker_stop_cancels_a_packaged_run_cleanly(tmp_path: Path) -> None:
    """SIGTERM reaches the app through the one-file bootloader: clean cancel, exit 1."""
    app, data = _app_dir(tmp_path), tmp_path / "data"
    data.mkdir()
    for index in range(6):
        synthetic.scanned_pdf(data / f"scan{index}.pdf", [synthetic.ENGLISH_LINES] * 6, dpi=300)
    originals = {p: sha256(p) for p in data.iterdir()}
    name = f"searchify-e2e-{uuid.uuid4().hex[:8]}"
    cmd = _docker_cmd(app, data, detached_name=name)
    subprocess.run(
        [*cmd, CLEAN_IMAGE, "/app/searchify-pdf", "--cli", "--jobs", "1", "/data"],
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
    assert "SIGTERM: cancelling" in logs and "cancelled" in logs
    assert not list(data.glob(".*")), "staging or lock files left behind"
    assert {p: sha256(p) for p in originals} == originals
    assert len(list(data.glob("*_searchable.pdf"))) < 6


def test_interactive_prompts_on_a_terminal(tmp_path: Path) -> None:
    """Existing copies → asked on a real pseudo-terminal: yes once, then skip the rest."""
    app, data = _app_dir(tmp_path), tmp_path / "data"
    data.mkdir()
    for name in ("a", "b", "c"):
        synthetic.scanned_pdf(data / f"{name}.pdf")
        (data / f"{name}_searchable.pdf").write_bytes(b"old copy")
    done = _docker(
        app,
        data,
        "-qec",
        "/app/searchify-pdf --cli /data",
        "/dev/null",
        stdin="y\ns\n",
        entry=("script",),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("[y]es / [n]o / [a]ll yes / [s]kip all / [c]ancel") == 2
    assert "1 converted · 0 copied · 2 skipped" in done.stdout
    replaced = [n for n in "abc" if (data / f"{n}_searchable.pdf").read_bytes() != b"old copy"]
    assert len(replaced) == 1
    assert contains_words(all_text(data / f"{replaced[0]}_searchable.pdf"), ["invoice"])


LAUNCHER_SCRIPT = r"""
set -eu
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp >/dev/null 2>&1 &
export DISPLAY=:99 XDG_DATA_HOME=/tmp/share
for _ in $(seq 50); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
/app/searchify-pdf --install-desktop-entry
entry="$(ls /tmp/share/applications/*.desktop)"
desktop-file-validate "$entry"
grep -q '^Exec=.*%F' "$entry"
gio launch "$entry" "/data/Ordner Ä" /data/single.pdf
for _ in $(seq 600); do
    [ -f "/data/Ordner Ä/inner_searchable.pdf" ] && [ -f /data/single_searchable.pdf ] && break
    sleep 0.2
done
xwininfo -root -tree | grep -q '"Searchify PDF"' && echo "window mapped"
ls "/data/Ordner Ä" /data
"""


def test_desktop_launcher_with_dropped_files_on_x11(tmp_path: Path) -> None:
    """The installed launcher started like a file manager does (gio launch, %F).

    A real X server shows the real window, which converts the dropped folder and file.
    A physical drag in a GNOME/KDE session stays a manual check (#7).
    """
    app, data = _app_dir(tmp_path), tmp_path / "data"
    (data / "Ordner Ä").mkdir(parents=True)
    synthetic.scanned_pdf(data / "Ordner Ä" / "inner.pdf")
    synthetic.scanned_pdf(data / "single.pdf")
    done = _docker(app, data, "-c", LAUNCHER_SCRIPT, image=X11_IMAGE, entry=("bash",))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "window mapped" in done.stdout, done.stdout + done.stderr
    assert contains_words(all_text(data / "Ordner Ä" / "inner_searchable.pdf"), ["invoice"])
    assert contains_words(all_text(data / "single_searchable.pdf"), ["invoice"])


def test_protected_pdfs_with_password_file_and_restricted_opt_in(tmp_path: Path) -> None:
    """ADR 0011 offline: the copies are searchable and protected like their originals."""
    import pikepdf

    app, data = _app_dir(tmp_path), tmp_path / "data"
    data.mkdir()
    synthetic.encrypted_pdf(data / "Statement.pdf")
    ndl = next(d for d in realcorpus.documents() if d.protected)
    shutil.copy2(ndl.path, data / ndl.file)
    originals = {p: sha256(p) for p in data.iterdir()}
    (app / "passwords.txt").write_text("wrong\nsecret\n", encoding="utf-8")
    done = _docker(
        app,
        data,
        "--cli",
        "--non-interactive",
        "--password-file",
        "/app/passwords.txt",
        "--process-restricted",
        "/data",
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "2 converted" in done.stdout and "secret" not in done.stdout
    statement = data / "Statement_searchable.pdf"
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(statement)
    assert contains_words(all_text(statement, "secret"), ["Searchable", "invoice"])
    restricted = data / ndl.copy_name
    assert contains_words(all_text(restricted), ndl.words)
    with pikepdf.open(ndl.path) as original, pikepdf.open(restricted) as copy:
        assert copy.allow == original.allow and not copy.owner_password_matched
    assert {p: sha256(p) for p in originals} == originals
    assert not list(data.glob(".*"))


def test_recognition_quality_of_the_packaged_engine(tmp_path: Path) -> None:
    """The bundled Tesseract meets the same ground-truth gate as the development setup."""
    from tests import quality

    app, data = _app_dir(tmp_path), tmp_path / "data"
    data.mkdir()
    for language, text in quality.TEXTS.items():
        for font in quality.FONTS:
            quality.render_pdf(data / f"{language}-{font}.pdf", text, font=font, dpi=200)
    shutil.copy2(quality.BGBL_IMAGE_ONLY, data / "bgbl.pdf")
    done = _docker(app, data, "--cli", "--non-interactive", "/data")
    assert done.returncode == 0, done.stdout + done.stderr
    for language, text in quality.TEXTS.items():
        for font in quality.FONTS:
            result = quality.score(text, all_text(data / f"{language}-{font}_searchable.pdf"))
            assert result.words >= 0.98, (language, font, str(result))
    real = quality.score(quality.bgbl_truth(), all_text(data / "bgbl_searchable.pdf"))
    assert real.words >= 0.92 and real.chars >= 0.98, str(real)
