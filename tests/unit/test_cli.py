# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""CLI behaviour: headless runs, overrides, non-interactive Ask, exit codes (A06, A09)."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

from searchify_pdf import __main__ as entry
from searchify_pdf.cli import main as cli
from searchify_pdf.domain.settings import (
    ExistingOutputPolicy,
    ExistingTextPolicy,
    Settings,
    SettingsError,
    UiLanguage,
    WorkerMode,
)
from searchify_pdf.storage.settings_repository import SETTINGS_FILE_NAME, SettingsRepository
from searchify_pdf.storage.statistics import STATS_FILE_NAME
from tests import synthetic
from tests.fakes import FakeEngine


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def run(
    argv: list[str],
    *,
    stdin: io.StringIO | None = None,
    engine: FakeEngine | None = None,
    gui: object = None,
) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(
        argv,
        stdin=stdin or io.StringIO(),
        stdout=out,
        engine_factory=lambda: engine or FakeEngine(),
        gui_launcher=gui,  # type: ignore[arg-type]
    )
    return code, out.getvalue()


def test_headless_convert_and_summary(tmp_path: Path) -> None:
    synthetic.scanned_pdf(tmp_path / "a.pdf")
    code, out = run(["--cli", str(tmp_path)])
    assert code == cli.EXIT_OK
    assert "[Converted]" in out and "1 converted" in out
    assert (tmp_path / "a_searchable.pdf").exists()


def test_noninteractive_ask_exit_code_3_and_override(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    (tmp_path / "a_searchable.pdf").write_bytes(b"old")
    code, out = run(["--cli", "--non-interactive", str(src)])
    assert code == cli.EXIT_ACTION_REQUIRED and "need a decision" in out
    assert (tmp_path / "a_searchable.pdf").read_bytes() == b"old"
    code, _ = run(["--cli", str(src)])  # stdin is not a TTY → also non-interactive
    assert code == cli.EXIT_ACTION_REQUIRED
    code, _ = run(["--cli", "--on-existing-output", "skip", str(src)])
    assert code == cli.EXIT_OK
    code, _ = run(["--cli", "--on-existing-output", "overwrite", str(src)])
    assert code == cli.EXIT_OK and (tmp_path / "a_searchable.pdf").read_bytes() != b"old"


def test_interactive_terminal_prompts(tmp_path: Path) -> None:
    srcs = [synthetic.scanned_pdf(tmp_path / f"{n}.pdf") for n in "abc"]
    for s in srcs:
        (tmp_path / f"{s.stem}_searchable.pdf").write_bytes(b"old")
    code, out = run(
        ["--cli", str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf"), str(tmp_path / "c.pdf")],
        stdin=Tty("x\nn\na\n"),
    )
    assert code == cli.EXIT_OK
    assert out.count("[y]es") == 3  # invalid answer repeated, then "n", then "a" for the rest
    assert (tmp_path / "a_searchable.pdf").read_bytes() == b"old"
    assert (tmp_path / "c_searchable.pdf").read_bytes() != b"old"
    digital = synthetic.digital_pdf(tmp_path / "d.pdf")
    code, out = run(["--cli", "--on-existing-text", "ask", str(digital)], stdin=Tty("s\n"))
    assert code == cli.EXIT_OK and "already has text on 1 of 1" in out
    (tmp_path / "d_searchable.pdf").unlink()
    code, _ = run(
        ["--cli", "--on-existing-text", "ask", str(digital)], stdin=Tty("")
    )  # EOF → cancel
    assert code == cli.EXIT_FAILED
    code, _ = run(["--cli", "--on-existing-text", "ask", str(digital)], stdin=Tty("c\n"))
    assert code == cli.EXIT_FAILED


def test_failure_exit_code_and_omissions(tmp_path: Path) -> None:
    synthetic.corrupt_pdf(tmp_path / "bad.pdf")
    (tmp_path / "x_searchable.pdf").write_bytes(b"%PDF")
    code, out = run(["--cli", "--ui-language", "de", str(tmp_path)])
    assert code == cli.EXIT_FAILED
    assert "Fehlgeschlagen" in out and "nicht verarbeitet" in out


def test_nothing_found(tmp_path: Path) -> None:
    code, out = run(["--cli", str(tmp_path)])
    assert code == cli.EXIT_OK and "No PDFs found." in out


def test_apply_overrides() -> None:
    args = cli.build_parser().parse_args(
        [
            "--on-existing-output",
            "overwrite",
            "--on-existing-text",
            "replace",
            "--languages",
            "deu+",
            "--suffix",
            "_ocr",
            "--deskew",
            "--no-rotate-pages",
            "--ui-language",
            "de",
            "--jobs",
            "4",
        ]
    )
    s = cli.apply_overrides(Settings(), args)
    assert s.existing_output_policy is ExistingOutputPolicy.OVERWRITE
    assert s.existing_text_policy is ExistingTextPolicy.ALWAYS_REPLACE
    assert s.ocr_languages == ("deu",) and s.output_suffix == "_ocr"
    assert s.deskew and not s.rotate_pages and s.ui_language is UiLanguage.GERMAN
    assert (s.worker_mode, s.fixed_workers) == (WorkerMode.FIXED, 4)
    parse = cli.build_parser().parse_args
    assert cli.apply_overrides(Settings(), parse(["--jobs", "auto"])).worker_mode is WorkerMode.AUTO
    assert (
        cli.apply_overrides(Settings(), parse(["--jobs", "1"])).worker_mode is WorkerMode.SEQUENTIAL
    )
    assert cli.apply_overrides(Settings(), parse([])) == Settings()
    with pytest.raises(SettingsError):
        cli.apply_overrides(Settings(), parse(["--jobs", "many"]))


def test_invalid_option_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = run(["--cli", "--jobs", "0", str(tmp_path)])
    assert code == cli.EXIT_USAGE
    assert "invalid option" in capsys.readouterr().err


def test_no_paths_headless_prints_help() -> None:
    code, out = run(["--cli"])
    assert code == cli.EXIT_USAGE and "usage:" in out


def test_overrides_are_not_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCHIFY_PDF_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    synthetic.scanned_pdf(tmp_path / "a.pdf")
    run(["--cli", "--suffix", "_ocr", str(tmp_path / "a.pdf")])
    assert (tmp_path / "a_ocr.pdf").exists()
    assert not (tmp_path / "home" / SETTINGS_FILE_NAME).exists()


def test_malformed_settings_warns_and_uses_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / SETTINGS_FILE_NAME).write_text("{oops")
    monkeypatch.setenv("SEARCHIFY_PDF_HOME", str(home))
    code, out = run(["--cli", str(tmp_path / "missing.pdf")])
    assert "could not be read" in out and code == cli.EXIT_OK


def test_statistics_recorded_only_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SEARCHIFY_PDF_HOME", str(home))
    synthetic.scanned_pdf(tmp_path / "a.pdf")
    run(["--cli", str(tmp_path / "a.pdf")])
    assert not (home / STATS_FILE_NAME).exists()  # off by default: nothing persisted
    SettingsRepository(home).save(Settings(statistics_enabled=True), None)
    run(["--cli", "--on-existing-output", "overwrite", str(tmp_path / "a.pdf")])
    data = json.loads((home / STATS_FILE_NAME).read_text())
    assert data["outcomes"] == {"converted": 1}
    (home / STATS_FILE_NAME).unlink()
    (home / STATS_FILE_NAME).mkdir()
    _, out = run(["--cli", "--on-existing-output", "overwrite", str(tmp_path / "a.pdf")])
    assert "Statistics could not be saved" in out
    assert (tmp_path / "a_searchable.pdf").exists()


def test_notes_are_printed(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "Report_searchable.pdf")
    _, out = run(["--cli", str(src)])
    assert "note: Name ends like a searchable copy" in out


def test_gui_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Settings, list[Path], Path]] = []

    def launcher(settings: Settings, paths: list[Path], app_dir: Path) -> int:
        calls.append((settings, paths, app_dir))
        return 0

    assert run(["--gui", str(tmp_path)], gui=launcher)[0] == 0
    assert calls[0][1] == [tmp_path]
    assert calls[0][2] == Path(os.environ["SEARCHIFY_PDF_HOME"])
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert run([], gui=launcher)[0] == 0 and calls[-1][1] == []
    import searchify_pdf.ui.app as ui_app

    monkeypatch.setattr(ui_app, "run_gui", launcher)
    assert cli.main(["--gui"], stdin=io.StringIO(), stdout=io.StringIO()) == 0


def test_gui_available() -> None:
    assert not cli.gui_available({}, "linux")
    assert cli.gui_available({"WAYLAND_DISPLAY": "w"}, "linux")
    assert cli.gui_available({}, "win32")


def test_gui_unavailable_without_pyside(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "PySide6", None)
    assert not cli.gui_available({"DISPLAY": ":0"}, "linux")


def test_licenses_and_desktop_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    code, out = run(["--licenses"])
    assert code == 0 and "ocrmypdf" in out.lower()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    code, out = run(["--install-desktop-entry"])
    assert code == 0 and out.strip().endswith("searchify-pdf.desktop")


def test_default_engine_factory() -> None:
    assert cli._default_engine().name == "ocrmypdf"


def test_entry_point_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert entry.main(["--searchify-engine-worker"]) == 1  # worker usage error, no GUI import
    assert entry.main(["--licenses"]) == 0
    monkeypatch.setattr(sys, "argv", ["searchify-pdf", "--licenses"])
    assert entry.main() == 0
    bundle = tmp_path / "bundle"
    (bundle / "bin").mkdir(parents=True)
    (bundle / "bin" / "tesseract").write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")
    assert entry.main(["--licenses"]) == 0
    assert os.environ["PATH"].startswith(str(bundle / "bin"))
    monkeypatch.delattr(sys, "_MEIPASS")
    assert entry.main(["--licenses"]) == 0
    capsys.readouterr()
