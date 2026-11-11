# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Qt application bootstrap.

``run_gui`` opens the main window. When paths were delivered by the OS (drop on the
launcher, "Open with", command line), they are queued, deduplicated and processed
immediately with the saved settings (VISION §3.1). Such a drop launch works in the
background unless *show window on drop* is enabled: no window, only the questions the
settings ask for, and a message at the end if anything needs attention.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from searchify_pdf import APP_ID, APP_NAME
from searchify_pdf.domain.jobs import BatchSummary
from searchify_pdf.domain.settings import Settings
from searchify_pdf.engines.base import OcrEngine
from searchify_pdf.platform.desktop import icon_bytes
from searchify_pdf.storage.settings_location import SettingsHome, current_settings_home
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
    home: SettingsHome | None = None,
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
    window = MainWindow(
        repository, engine_factory, run_overrides=overrides, app_dir=app_dir, home=home
    )
    apply_theme(app, window.saved.theme)
    app.installEventFilter(FileOpenFilter(window))
    if paths:
        window.add_paths(paths)
        QTimer.singleShot(0, window.start)
    return app, window


def run_in_background(app: QApplication, window: MainWindow) -> None:
    """Process the dropped paths without showing ``window`` (the default drop launch).

    Questions (passwords, "overwrite?") still appear as dialogs. When the batch ends the
    app quits with 0 if everything succeeded; otherwise a message offers the window with
    the details (Yes) or quits with 1 (No).
    """
    app.setQuitOnLastWindowClosed(False)  # closing a question dialog must not quit

    def finished(summary: BatchSummary) -> None:
        if window.running:  # a further drop arrived meanwhile and was started
            return
        window.batch_done = None
        if summary.succeeded:
            app.exit(0)
            return
        answer = window.message(
            QMessageBox.Icon.Warning,
            APP_NAME,
            window.t("background.attention", summary=window.summary_label.text()),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            app.setQuitOnLastWindowClosed(True)
            window.show()
        else:
            app.exit(1)

    window.batch_done = finished


def smoke_test(
    settings: Settings,
    paths: list[Path],
    app_dir: Path,
    *,
    timeout_seconds: float = 600.0,
    engine_factory: Callable[[], OcrEngine] = _default_engine,
) -> int:
    """Open the real window (e.g. offscreen), run a drop launch for ``paths`` and exit.

    Used by the packaged end-to-end test to prove the frozen GUI starts and processes a
    dropped folder with the saved settings. Prints one line and returns 0 on success.
    """
    app, window = create_window(settings, paths, app_dir, engine_factory)
    window.show()
    deadline = time.monotonic() + timeout_seconds
    app.processEvents()
    while (window.running or (paths and window.last_summary is None)) and (
        time.monotonic() < deadline
    ):
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    summary = window.last_summary
    ok = summary.succeeded if summary is not None else not paths
    print(f"gui-smoke {'ok' if ok else 'failed'}: {window.summary_label.text()!r}", flush=True)
    window.close()
    return 0 if ok else 1


def run_gui(settings: Settings, paths: list[Path], app_dir: Path) -> int:  # pragma: no cover
    home = current_settings_home()
    app, window = create_window(settings, paths, app_dir, home=home)
    if paths and not window.run_settings().show_window_on_drop:
        run_in_background(app, window)
    else:
        window.show()
    return int(app.exec())
