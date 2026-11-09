# 0001 — Python 3.12 baseline and PySide6 (Qt Widgets)

- Status: accepted
- Date: 2026-11-09

## Context
VISION §6.3/§9 asks for a polished, accessible, themeable desktop UI on Linux first, then
Windows 10/11 and macOS (Intel + Apple Silicon), with native open events and a small
licensing risk. OCRmyPDF 17 needs Python ≥ 3.11.

## Decision
- Python **3.12** as the runtime baseline (supported by Windows 10, all OCRmyPDF/PySide6
  wheels; CI also tests 3.13).
- **PySide6-Essentials 6.12** (Qt Widgets). LGPL-3.0 allows dynamic linking from a GPL
  application; Essentials avoids WebEngine and other heavy add-ons.
- Business logic is Qt-free; only `searchify_pdf.ui` imports Qt.

## Alternatives
Tkinter (weak theming/accessibility, no native open events), wxPython (larger packaging
friction), PyQt6 (GPL/commercial; would also work but PySide6 keeps options open).

## Consequences
Qt gives `QFileOpenEvent` for macOS, high-DPI, dark/light palettes and offscreen testing
(`pytest-qt`). The bundle is ~130 MB.
