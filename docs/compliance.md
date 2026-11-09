# Distribution compliance checklist

This is a release checklist, not legal advice (VISION §13).

| Item | How it is satisfied |
| --- | --- |
| Project license | GPL-3.0-or-later (`LICENSE`), SPDX headers checked by `scripts/check_headers.py` |
| Inventory of bundled components | `scripts/generate_inventory.py` → `components.json` (release asset, About tab, `--licenses`). Generated from the build container: runtime Python dependency closure, Qt, Python runtime, PyInstaller bootloader, Tesseract and every Debian package of a library it links, language data with SHA-256 |
| License texts | Collected into the bundle (`licenses/`): Python `.dist-info` license files, Debian `copyright` files of native libraries, project `LICENSE` |
| LGPL (Qt/PySide6, img2pdf, fpdf2) | Shared libraries/modules remain replaceable in principle; source is available from upstream (qt.io / PyPI sdists) at the listed exact versions |
| GPL-2+/GPL-3 native libs (e.g. libjbig, libacl, libicu) | Compatible with GPL-3.0-or-later; source via `apt-get source <package>=<version>` on Ubuntu 22.04 (versions in the inventory) |
| Apache-2.0 (Tesseract, tessdata, PDFium) | License texts and notices bundled |
| AGPL Ghostscript | Not bundled (no PDF/A output) |
| Complete corresponding source | Tagged commit + `searchify_pdf-<version>-source.tar.gz` release asset; build scripts and Dockerfiles are part of the source |
| Name/trademark "Searchify PDF" | **Open** — working title, not yet checked (owner decision) |
| Code signing / publisher identity | **Open** — not required for Linux prerelease; required decision before Windows/macOS |
