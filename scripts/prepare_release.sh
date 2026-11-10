#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# prepare_release.sh — collect the already built and tested artifacts into a release folder.
#
# Usage: scripts/prepare_release.sh VERSION OUT_DIR [PREVIOUS_VERSION]
#
# PREVIOUS_VERSION is the version of the last *published* release: the notes then list
# every CHANGELOG entry since it. Without it (first public release) the notes give the
# highlights and link the full CHANGELOG.
# Copies every executable of VERSION from dist/binary (Linux, and Windows/macOS when the
# release workflow downloaded them) with its component inventory, the wheel and sdist
# from dist/, the GPL license, and writes SHA256SUMS and RELEASE_NOTES.md (commit,
# downloads, changelog entry, known limitations, source offer). Nothing is rebuilt here.
# The Linux executable is required; the others are listed when present.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:?version}"
OUT="${2:?out dir}"
PREVIOUS="${3:-}"
BIN="${ROOT_DIR}/dist/binary"
LINUX="searchify-pdf-${VERSION}-linux-x86_64"
WINDOWS="searchify-pdf-${VERSION}-windows-x86_64.exe"
MACOS="searchify-pdf-${VERSION}-macos-arm64"
rm -rf "${OUT}" && mkdir -p "${OUT}"
test -f "${BIN}/${LINUX}" || { echo "missing ${BIN}/${LINUX}" >&2; exit 1; }
for name in "${LINUX}" "${WINDOWS}" "${MACOS}"; do
    if [[ -f "${BIN}/${name}" ]]; then
        cp "${BIN}/${name}" "${BIN}/${name}.components.json" "${OUT}/"
    fi
done
cp "${ROOT_DIR}"/dist/searchify_pdf-"${VERSION}"*.whl "${OUT}/"
cp "${ROOT_DIR}"/dist/searchify_pdf-"${VERSION}".tar.gz "${OUT}/searchify_pdf-${VERSION}-source.tar.gz"
cp "${ROOT_DIR}/LICENSE" "${OUT}/LICENSE.txt"
COMMIT="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
{
    echo "# Searchify PDF ${VERSION}"
    echo
    echo "Drop scanned PDFs or whole folders and get a searchable copy beside each original."
    echo "Text recognition runs locally (OCRmyPDF + Tesseract, English and German bundled);"
    echo "nothing is uploaded and originals are never modified."
    echo
    echo "Built from commit \`${COMMIT}\` by the release workflow."
    echo
    echo "## Download"
    echo
    echo "| Platform | File | Tested by the release workflow |"
    echo "| --- | --- | --- |"
    echo "| 🐧 Linux x86-64 (glibc ≥ 2.35: Ubuntu 22.04+, Debian 12+, Fedora 36+) | \`${LINUX}\` | full pipeline: unit, integration with real OCR, UI, coverage gates, packaged E2E in clean offline containers |"
    if [[ -f "${OUT}/${WINDOWS}" ]]; then
        echo "| 🪟 Windows 10/11 x86-64 — **preview** | \`${WINDOWS}\` | smoke tests of the built executable: version, licenses, GUI drop (offscreen), CLI conversion with the bundled Tesseract |"
    fi
    if [[ -f "${OUT}/${MACOS}" ]]; then
        echo "| 🍎 macOS 15+ Apple silicon (arm64) — **preview** | \`${MACOS}\` | same smoke tests as Windows |"
    fi
    echo
    echo "Verify the download: \`sha256sum -c SHA256SUMS --ignore-missing\`."
    echo
    echo "- **Linux:** \`chmod +x ${LINUX} && ./${LINUX}\` opens the window;"
    echo "  \`./${LINUX} --install-desktop-entry\` adds an app-menu launcher that accepts dropped PDFs and folders."
    if [[ -f "${OUT}/${WINDOWS}" ]]; then
        echo "- **Windows:** the executable is not code-signed yet. SmartScreen may warn: *More info → Run anyway*."
        echo "  A console window opens next to the app window (it also serves the \`--cli\` mode)."
    fi
    if [[ -f "${OUT}/${MACOS}" ]]; then
        echo "- **macOS:** the executable is not notarized yet. In Terminal:"
        echo "  \`xattr -d com.apple.quarantine ${MACOS}; chmod +x ${MACOS}; ./${MACOS}\`."
    fi
    echo "- Settings are stored in \`searchify-pdf.settings.json\` beside the executable (portable). If that folder is read-only,"
    echo "  the app offers to keep them in your user profile instead (\`--store-settings-in-profile\` on the command line)."
    echo "- \`*.components.json\` lists every bundled component and its license (also under About in the app)."
    echo "- Wheel and source archive for Python users; \`docker pull ghcr.io/marcelpetrick/searchifymypdf:${VERSION}\` for the headless CLI image."
    echo
    echo "## Changes"
    echo
    if [[ -n "${PREVIOUS}" ]]; then
        echo "Since ${PREVIOUS}:"
        echo
        awk -v from="## ${VERSION} " -v to="## ${PREVIOUS} " \
            'index($0, to) == 1 {exit} index($0, from) == 1 {on=1} on && /^- / {print}' \
            "${ROOT_DIR}/CHANGELOG.md"
    else
        echo "First public release. Highlights:"
        echo
        echo "- Drop PDFs or whole folders (recursive) on the window or the installed launcher; copies are written beside the originals with a configurable suffix, originals are never modified."
        echo "- Safe publishing: staged, validated and atomically published; failures, cancellation, full disks or crashes never damage an earlier copy."
        echo "- Keep or replace existing text, overwrite/skip/ask for existing copies, bounded parallel processing, clean cancel."
        echo "- Password-protected PDFs: the password is asked for and the copy keeps it; PDFs with usage restrictions on request, the copy keeps them."
        echo "- English and German recognition (German umlauts included), verified against full ground truth."
        echo "- English/German interface, light/dark themes, portable settings, optional local statistics, offline licenses."
        echo "- Headless CLI and Docker image (\`ghcr.io/marcelpetrick/searchifymypdf\`)."
        echo
        echo "Full history: [CHANGELOG.md](https://github.com/marcelpetrick/SearchifyMyPDF/blob/${COMMIT}/CHANGELOG.md)."
    fi
    echo
    echo "## Known limitations"
    echo
    echo "- Windows and macOS builds are previews: smoke-tested, not yet covered by the full test suite, unsigned."
    echo "- Digitally signed PDFs are rejected (a copy would invalidate the signature); originals stay untouched."
    echo "- Pages mixing digital text with scanned regions keep their existing text unchanged in 'keep existing text' mode."
    echo "- Bundled OCR languages: English and German. Handwriting and poor scans are not guaranteed."
    echo "- Dropping onto the raw Linux executable depends on the file manager; use the installed launcher or the window."
    echo
    echo "## License and source"
    echo
    echo "GPL-3.0-or-later. The complete corresponding source is the tagged commit and the attached source archive."
    echo "Bundled third-party components and their licenses are listed in the inventories; Debian source packages for the"
    echo "native libraries in the Linux build are available from the Ubuntu 22.04 archive (\`apt-get source <package>\`),"
    echo "Tesseract and Leptonica sources from their upstream projects."
} > "${OUT}/RELEASE_NOTES.md"
(cd "${OUT}" && sha256sum -- * > SHA256SUMS)
ls -la "${OUT}"
