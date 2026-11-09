#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Capture real screenshots of the running UI for the README.

Usage::

    QT_QPA_PLATFORM=offscreen scripts/screenshot.py [OUT_DIR]   (default: docs/media)

Builds a small synthetic corpus in a temporary folder, opens the real main window with
the real OCR engine, processes the folder (drop launch) and saves:
``screenshot-convert-light.png``, ``screenshot-convert-dark.png`` and
``screenshot-settings-de.png``.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from PySide6.QtWidgets import QApplication  # noqa: E402
from tests import synthetic  # noqa: E402

from searchify_pdf.domain.settings import Settings, Theme, UiLanguage  # noqa: E402
from searchify_pdf.storage.settings_repository import SettingsRepository  # noqa: E402
from searchify_pdf.ui.app import create_window  # noqa: E402
from searchify_pdf.ui.theme import apply_theme  # noqa: E402


def wait(app: QApplication, condition: object, timeout: float = 300) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:  # type: ignore[operator]
        app.processEvents()
        time.sleep(0.02)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "media"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        home = base / "app"
        home.mkdir()
        docs = base / "Scans 2025"
        (docs / "Verträge").mkdir(parents=True)
        (docs / "Invoices").mkdir()
        synthetic.scanned_pdf(docs / "Invoices" / "Invoice 0815.pdf")
        synthetic.scanned_pdf(
            docs / "Invoices" / "Invoice 0816.pdf", (synthetic.ENGLISH_LINES,) * 2
        )
        synthetic.scanned_pdf(docs / "Verträge" / "Mietvertrag.pdf", (synthetic.GERMAN_LINES,))
        synthetic.digital_pdf(docs / "Born digital report.pdf")
        synthetic.encrypted_pdf(docs / "Locked statement.pdf")
        SettingsRepository(home).save(Settings(theme=Theme.LIGHT), None)
        app, window = create_window(Settings(theme=Theme.LIGHT), [docs], home)
        window.resize(1100, 720)
        window.show()
        wait(app, lambda: window.last_summary is not None and not window.running)
        window.table.resizeColumnsToContents()
        app.processEvents()
        window.grab().save(str(out / "screenshot-convert-light.png"))
        apply_theme(app, Theme.DARK)
        app.processEvents()
        window.grab().save(str(out / "screenshot-convert-dark.png"))
        apply_theme(app, Theme.LIGHT)
        window.ui_language_combo.setCurrentIndex(
            window.ui_language_combo.findData(UiLanguage.GERMAN.value)
        )
        window.save_settings()
        window.tabs.setCurrentIndex(1)
        app.processEvents()
        window.grab().save(str(out / "screenshot-settings-de.png"))
        window.close()
    for name in sorted(out.glob("screenshot-*.png")):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
