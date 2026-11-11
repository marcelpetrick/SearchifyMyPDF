# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Opt-in user-profile settings without breaking portable mode (ADR 0012, issue #9)."""

from __future__ import annotations

import io
import os
import stat
from pathlib import Path

import pytest

from searchify_pdf.cli import main as cli
from searchify_pdf.domain.settings import Settings
from searchify_pdf.platform import app_location
from searchify_pdf.platform.app_location import profile_directory
from searchify_pdf.storage import settings_location
from searchify_pdf.storage.settings_location import (
    Location,
    current_settings_home,
    resolve_settings_home,
    store_settings,
)
from searchify_pdf.storage.settings_repository import SETTINGS_FILE_NAME, SettingsRepository

HOME = Path("/home/u")


@pytest.mark.parametrize(
    ("system", "env", "expected"),
    [
        (
            "Windows",
            {"APPDATA": "C:/Users/u/AppData/Roaming"},
            "C:/Users/u/AppData/Roaming/Searchify PDF",
        ),
        ("Windows", {}, "/home/u/AppData/Roaming/Searchify PDF"),
        ("Darwin", {}, "/home/u/Library/Application Support/Searchify PDF"),
        pytest.param(
            "Linux",
            {"XDG_CONFIG_HOME": "/cfg"},
            "/cfg/searchify-pdf",
            marks=pytest.mark.skipif(os.name == "nt", reason="/cfg is not absolute on Windows"),
        ),
        ("Linux", {"XDG_CONFIG_HOME": "relative"}, "/home/u/.config/searchify-pdf"),
        ("Linux", {}, "/home/u/.config/searchify-pdf"),
    ],
)
def test_profile_directory_per_platform(system: str, env: dict[str, str], expected: str) -> None:
    assert profile_directory(env=env, system=system, home=HOME) == Path(expected)


def test_current_profile_directory_is_below_the_home_or_config_folder() -> None:
    got = app_location.current_profile_directory()
    assert got.name in {"searchify-pdf", "Searchify PDF"}


def test_resolution_order(tmp_path: Path) -> None:
    app, profile = tmp_path / "app", tmp_path / "profile"
    app.mkdir()
    profile.mkdir()
    # nothing anywhere, or only an empty profile folder: portable (no silent fallback)
    home = resolve_settings_home(app, profile, overridden=False)
    assert (home.directory, home.location) == (app, Location.PORTABLE)
    # the opt-in left a settings file in the profile: use it
    SettingsRepository(profile).save(Settings(), None)
    home = resolve_settings_home(app, profile, overridden=False)
    assert (home.directory, home.location) == (profile, Location.PROFILE)
    # a settings file next to the app always wins
    SettingsRepository(app).save(Settings(), None)
    home = resolve_settings_home(app, profile, overridden=False)
    assert (home.directory, home.location) == (app, Location.PORTABLE)
    # the override wins over both
    home = resolve_settings_home(app, profile, overridden=True)
    assert (home.directory, home.location, home.profile_dir) == (app, Location.OVERRIDE, profile)


def test_current_settings_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert current_settings_home().location is Location.OVERRIDE  # conftest sets the override
    monkeypatch.delenv(app_location.HOME_OVERRIDE)
    monkeypatch.setattr(settings_location, "current_application_directory", lambda: tmp_path)
    monkeypatch.setattr(settings_location, "current_profile_directory", lambda: tmp_path / "p")
    home = current_settings_home()
    assert (home.directory, home.location) == (tmp_path, Location.PORTABLE)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_store_settings_creates_a_private_folder(tmp_path: Path) -> None:
    target = tmp_path / "cfg" / "searchify-pdf"
    store_settings(target, Settings(ocr_languages=("deu",)))
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert SettingsRepository(target).load().settings.ocr_languages == ("deu",)
    store_settings(target, Settings())  # saving again over its own file is not "stale"
    assert SettingsRepository(target).load().settings == Settings()


@pytest.fixture
def portable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """No override: the app folder and the profile folder of a real installation."""
    app, profile = tmp_path / "app", tmp_path / "profile" / "searchify-pdf"
    app.mkdir()
    monkeypatch.delenv(app_location.HOME_OVERRIDE)
    monkeypatch.setattr(settings_location, "current_application_directory", lambda: app)
    monkeypatch.setattr(settings_location, "current_profile_directory", lambda: profile)
    return app, profile


def run(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    return cli.main(argv, stdin=io.StringIO(), stdout=out), out.getvalue()


def test_cli_opt_in_stores_the_effective_settings_in_the_profile(
    portable: tuple[Path, Path],
) -> None:
    app, profile = portable
    code, out = run(["--store-settings-in-profile", "--languages", "deu", "--suffix", "_ocr"])
    assert code == cli.EXIT_OK
    assert f"user profile: {profile}" in out and "precedence" not in out
    saved = SettingsRepository(profile).load().settings
    assert saved.ocr_languages == ("deu",) and saved.output_suffix == "_ocr"
    assert not (app / SETTINGS_FILE_NAME).exists()
    home = current_settings_home()
    assert (home.directory, home.location) == (profile, Location.PROFILE)


def test_cli_opt_in_warns_when_a_portable_file_takes_precedence(
    portable: tuple[Path, Path],
) -> None:
    app, profile = portable
    SettingsRepository(app).save(Settings(), None)
    code, out = run(["--store-settings-in-profile"])
    assert code == cli.EXIT_OK and "takes precedence" in out
    assert (profile / SETTINGS_FILE_NAME).is_file()
    assert current_settings_home().location is Location.PORTABLE


def test_cli_opt_in_reports_an_unwritable_profile(
    portable: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _app, profile = portable
    profile.parent.parent.mkdir(exist_ok=True)
    profile.parent.write_text("a file where a folder should be")
    code, _out = run(["--store-settings-in-profile"])
    assert code == cli.EXIT_FAILED
    assert "Saving failed" in capsys.readouterr().err


def test_cli_opt_in_is_refused_with_the_home_override(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _out = run(["--store-settings-in-profile"])
    assert code == cli.EXIT_USAGE
    assert "SEARCHIFY_PDF_HOME is set" in capsys.readouterr().err
