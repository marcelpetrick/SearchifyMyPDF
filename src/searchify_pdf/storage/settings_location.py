# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Which folder holds the settings and statistics files (VISION §6.2, ADR 0012).

Portable by default: the folder beside the application. The user-profile folder is
used only after the user explicitly chose it (the GUI button or
``--store-settings-in-profile``); that choice is recorded by the settings file existing
there. A settings file beside the application always takes precedence, and
``SEARCHIFY_PDF_HOME`` overrides both. There is no silent fallback: a read-only
application folder without that choice keeps showing the guidance to move the app.
"""

from __future__ import annotations

import dataclasses
import enum
import os
from pathlib import Path

from searchify_pdf.domain.settings import Settings
from searchify_pdf.platform.app_location import (
    HOME_OVERRIDE,
    current_application_directory,
    current_profile_directory,
)
from searchify_pdf.storage.settings_repository import SETTINGS_FILE_NAME, SettingsRepository


class Location(enum.StrEnum):
    OVERRIDE = "override"  # SEARCHIFY_PDF_HOME (tests, Docker /config)
    PORTABLE = "portable"  # beside the application (default)
    PROFILE = "profile"  # the user's profile folder, after an explicit opt-in


@dataclasses.dataclass(frozen=True, slots=True)
class SettingsHome:
    directory: Path  # where settings and statistics are read and written
    location: Location
    app_dir: Path
    profile_dir: Path


def resolve_settings_home(app_dir: Path, profile_dir: Path, *, overridden: bool) -> SettingsHome:
    """Pick the settings folder: override → file beside the app → opted-in profile → app."""
    if overridden:
        return SettingsHome(app_dir, Location.OVERRIDE, app_dir, profile_dir)
    if not (app_dir / SETTINGS_FILE_NAME).exists() and (profile_dir / SETTINGS_FILE_NAME).is_file():
        return SettingsHome(profile_dir, Location.PROFILE, app_dir, profile_dir)
    return SettingsHome(app_dir, Location.PORTABLE, app_dir, profile_dir)


def current_settings_home() -> SettingsHome:
    """:func:`resolve_settings_home` for the running process."""
    return resolve_settings_home(
        current_application_directory(),
        current_profile_directory(),
        overridden=bool(os.environ.get(HOME_OVERRIDE)),
    )


def store_settings(directory: Path, settings: Settings) -> str:
    """Save ``settings`` into ``directory`` (created private if missing); return fingerprint.

    Raises :class:`~searchify_pdf.storage.settings_repository.SettingsSaveError` or
    :class:`OSError` when the folder cannot be created or written.
    """
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    repository = SettingsRepository(directory)
    return repository.save(settings, repository.load().fingerprint)
