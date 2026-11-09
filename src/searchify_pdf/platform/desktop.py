# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Desktop integration: Linux launcher (drop target / "Open with") and "Open folder".

Dropping files onto a raw executable is not supported by every Linux file manager
(VISION §10). Installing a freedesktop ``.desktop`` launcher with ``Exec=… %F`` and the
PDF + folder MIME types makes the app a drop target in docks/menus that honour it and
adds it to "Open with". File/folder pickers remain the universal fallback.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping
from importlib import resources
from pathlib import Path

from searchify_pdf import APP_ID, APP_NAME
from searchify_pdf.platform.runtime import external_env

DESKTOP_TEMPLATE = """[Desktop Entry]
Type=Application
Version=1.5
Name={name}
GenericName=PDF text recognition
Comment=Make scanned PDFs searchable
Exec={exec} %F
Icon={icon}
Terminal=false
Categories=Office;Utility;
MimeType=application/pdf;inode/directory;
Keywords=OCR;PDF;scan;searchable;
StartupWMClass=searchify-pdf
"""


def launch_command(*, frozen: bool, executable: str, appimage: str | None) -> list[str]:
    """How the launcher should start this application."""
    if appimage:
        return [appimage]
    if frozen:
        return [executable]
    return [executable, "-m", "searchify_pdf"]


def icon_bytes() -> bytes:
    return resources.files("searchify_pdf").joinpath("resources/searchify-pdf.svg").read_bytes()


def install_desktop_entry(data_home: Path, command: list[str]) -> Path:
    """Write the launcher and icon below ``data_home`` (``~/.local/share``)."""
    apps = data_home / "applications"
    icons = data_home / "icons" / "hicolor" / "scalable" / "apps"
    apps.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)
    icon = icons / f"{APP_ID}.svg"
    icon.write_bytes(icon_bytes())
    entry = apps / f"{APP_ID}.desktop"
    exec_line = " ".join(shlex.quote(part) for part in command)
    entry.write_text(
        DESKTOP_TEMPLATE.format(name=APP_NAME, exec=exec_line, icon=icon), encoding="utf-8"
    )
    entry.chmod(0o755)
    return entry


def default_data_home(env: Mapping[str, str]) -> Path:
    return Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def open_folder(
    folder: Path,
    *,
    platform: str = sys.platform,
    popen: Callable[..., object] = subprocess.Popen,
) -> None:
    """Open ``folder`` in the system file manager (never blocks)."""
    if platform.startswith("win"):
        command = ["explorer", str(folder)]
    elif platform == "darwin":
        command = ["open", str(folder)]
    else:
        command = ["xdg-open", str(folder)]
    popen(command, env=external_env(os.environ), start_new_session=True)
