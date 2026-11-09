# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Qt application bootstrap.

``run_gui`` opens the main window. When paths were delivered by the OS (drop on the
launcher, "Open with", command line), they are queued, deduplicated and processed
immediately with the saved settings (VISION §3.1).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from searchify_pdf import APP_ID, APP_NAME
from searchify_pdf.domain.settings import Settings
from searchify_pdf.engines.base import OcrEngine
from searchify_pdf.platform.desktop import icon_bytes
from searchify_pdf.storage.settings_repository import SettingsRepository
from searchify_pdf.ui.main_window import FileOpenFilter, MainWindow
from searchify_pdf.ui.theme import apply_theme


def _default_engine() -> OcrEngine:
    from searchify_pdf.engines.ocrmypdf_engine import OcrmypdfEngine

    return OcrmypdfEngine()


def create_window(
    settings: Settings,
    paths: list[Path],
    app_dir: Path,
    engine_factory: Callable[[], OcrEngine] = _default_engine,
) -> tuple[QApplication, MainWindow]:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    pixmap = QPixmap()
    pixmap.loadFromData(icon_bytes())
    app.setWindowIcon(QIcon(pixmap))
    repository = SettingsRepository(app_dir)
    saved = repository.load().settings
    overrides = settings if settings != saved else None
    window = MainWindow(repository, engine_factory, run_overrides=overrides, app_dir=app_dir)
    apply_theme(app, window.saved.theme)
    app.installEventFilter(FileOpenFilter(window))
    if paths:
        window.add_paths(paths)
        QTimer.singleShot(0, window.start)
    return app, window


def run_gui(settings: Settings, paths: list[Path], app_dir: Path) -> int:  # pragma: no cover
    app, window = create_window(settings, paths, app_dir)
    window.show()
    return int(app.exec())
