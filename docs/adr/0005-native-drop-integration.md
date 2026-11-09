# 0005 — Drop integration on Linux

- Status: accepted
- Date: 2026-11-09

## Context
Dropping onto a raw ELF is not supported uniformly by Linux file managers (§10).

## Decision
- The app accepts paths as arguments; with paths it opens the window and starts at once
  with the saved settings (drop launch). Without paths it opens the window.
- `searchify-pdf --install-desktop-entry` (also a button in About) writes a freedesktop
  launcher with `Exec=… %F` and `MimeType=application/pdf;inode/directory;` and an icon.
  Docks/menus that honour it accept drops; it also adds "Open with".
- The window has its own drop zone; Add PDFs/Add folder are the universal fallback.
- macOS `QFileOpenEvent`s are queued and started (code present, not yet validated).

## Consequences
Drop behaviour depends on the desktop; see `docs/desktop-matrix.md`.
