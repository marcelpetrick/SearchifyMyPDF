# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Light/dark themes: restrained, colorful accents with good contrast (VISION §6.3)."""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from searchify_pdf.domain.settings import Theme


@dataclasses.dataclass(frozen=True, slots=True)
class Colors:
    window: str
    surface: str
    text: str
    muted: str
    accent: str
    accent_text: str
    accent2: str
    border: str
    selection: str
    success: str
    warning: str
    danger: str


# Light: neutral grey-white surfaces (no lavender wash), one violet accent, teal second
# accent; text/muted/accent all ≥ 4.5:1 on both window and surface.
LIGHT = Colors(
    window="#f3f4f8",
    surface="#ffffff",
    text="#1f2330",
    muted="#596072",
    accent="#5b3fd1",
    accent_text="#ffffff",
    accent2="#0f766e",
    border="#d5d8e2",
    selection="#e8e3fb",
    success="#15803d",
    warning="#a16207",
    danger="#b91c1c",
)
DARK = Colors(
    window="#16131f",
    surface="#221d30",
    text="#f1eefc",
    muted="#b7b0d1",
    accent="#a78bfa",
    accent_text="#16131f",
    accent2="#22d3ee",
    border="#3b3452",
    selection="#3a3058",
    success="#4ade80",
    warning="#facc15",
    danger="#f87171",
)


def resolve(theme: Theme) -> Colors:
    if theme is Theme.LIGHT:
        return LIGHT
    if theme is Theme.DARK:
        return DARK
    hints = QGuiApplication.styleHints()
    return DARK if hints.colorScheme() == Qt.ColorScheme.Dark else LIGHT


def stylesheet(c: Colors) -> str:
    return f"""
    QWidget {{ color: {c.text}; font-size: 10.5pt; }}
    QMainWindow, QDialog {{ background: {c.window}; }}
    QTabWidget::pane {{ border: 1px solid {c.border}; border-radius: 10px; background: {c.surface}; top: -1px; }}
    QTabBar::tab {{ padding: 8px 18px; margin: 2px; border-radius: 8px; color: {c.muted}; }}
    QTabBar::tab:hover:!selected {{ color: {c.text}; background: {c.selection}; }}
    QTabBar::tab:selected {{ background: {c.accent}; color: {c.accent_text}; }}
    QTabBar::tab:focus {{ outline: 2px solid {c.accent2}; }}
    QLabel#title {{ font-size: 20pt; font-weight: 700; color: {c.accent}; }}
    QLabel#tagline {{ color: {c.muted}; font-size: 11pt; }}
    QFrame#dropZone {{
        border: 2px dashed {c.accent2}; border-radius: 14px; background: {c.window};
        min-height: 110px;
    }}
    QFrame#dropZone[active="true"] {{ border: 3px solid {c.accent}; background: {c.selection}; }}
    QLabel#dropHint {{ font-size: 13pt; font-weight: 600; }}
    QLabel#dropSubhint, QLabel#hint {{ color: {c.muted}; }}
    QPushButton {{
        padding: 7px 16px; border-radius: 8px; border: 1px solid {c.border};
        background: {c.surface};
    }}
    QPushButton:hover {{ border-color: {c.accent}; }}
    QPushButton:focus {{ border: 2px solid {c.accent2}; }}
    QPushButton:disabled {{ color: {c.muted}; }}
    QPushButton#primary {{ background: {c.accent}; color: {c.accent_text}; border: none; font-weight: 700; }}
    QPushButton#primary:disabled {{ background: {c.border}; color: {c.muted}; }}
    QLineEdit {{
        padding: 5px 8px; border: 1px solid {c.border}; border-radius: 6px;
        background: {c.surface}; selection-background-color: {c.accent};
        selection-color: {c.accent_text};
    }}
    QLineEdit:focus {{ border: 1px solid {c.accent}; }}
    QComboBox QAbstractItemView {{ background: {c.surface}; border: 1px solid {c.border};
        selection-background-color: {c.selection}; selection-color: {c.text}; }}
    QProgressBar {{ border: none; border-radius: 4px; background: {c.border}; }}
    QProgressBar::chunk {{ border-radius: 4px; background: {c.accent2}; }}
    QTableWidget {{ background: {c.surface}; alternate-background-color: {c.window};
        border: 1px solid {c.border}; border-radius: 8px;
        selection-background-color: {c.selection}; selection-color: {c.text}; }}
    QTableWidget::item {{ padding: 4px 8px; border: none; }}
    QHeaderView::section {{ background: {c.surface}; color: {c.muted}; padding: 6px 8px;
        border: none; border-bottom: 1px solid {c.border}; font-weight: 600; }}
    QToolTip {{ background: {c.surface}; color: {c.text}; border: 1px solid {c.border}; padding: 4px; }}
    QGroupBox {{ border: 1px solid {c.border}; border-radius: 10px; margin-top: 14px; padding: 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {c.accent}; font-weight: 700; }}
    QLabel#summary {{ font-weight: 600; }}
    QLabel#warning {{ color: {c.warning}; font-weight: 600; }}
    QLabel#error {{ color: {c.danger}; font-weight: 600; }}
    QLabel#ok {{ color: {c.success}; font-weight: 600; }}
    """


def apply_theme(app: QApplication, theme: Theme) -> Colors:
    colors = resolve(theme)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors.window))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors.surface))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors.window))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors.text))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors.text))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(colors.surface))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors.accent_text))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors.surface))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors.text))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet(colors))
    return colors
