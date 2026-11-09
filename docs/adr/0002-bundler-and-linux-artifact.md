# 0002 — PyInstaller one-file executable built on Ubuntu 22.04

- Status: accepted
- Date: 2026-11-09

## Context
Users must not install Python or Tesseract (VISION §10). Linux first: "AppImage or a
validated equivalent". Settings must live beside the real application file.

## Decision
- **PyInstaller 6** in `--onefile` mode, spec in `packaging/linux/searchify-pdf.spec`.
- Built inside `packaging/linux/Dockerfile.build` (**Ubuntu 22.04**, glibc 2.35 baseline).
- Bundles `tesseract` (4.1.1 from Ubuntu) into `bin/`, its shared libraries, the pinned
  `tessdata_fast` eng/deu/osd data, the component inventory and license texts.
- At startup the frozen app prepends `<bundle>/bin` to `PATH` and sets
  `TESSDATA_PREFIX`; system helpers get the original `LD_LIBRARY_PATH` back.
- `sys.executable` of a one-file app is the file the user launched, so the settings
  file lands beside it — never in the temporary extraction directory.

## Validation
`scripts/e2e_packaged.sh` runs the artifact in clean, offline Ubuntu 22.04 containers
without Python/Tesseract (CLI, portable settings, read-only app folder, GUI offscreen).

## Consequences
One file per OS/architecture. AppImage desktop integration is replaced by an explicit
`--install-desktop-entry` launcher (ADR 0005). Start-up extracts to a temp dir (~1 s).
