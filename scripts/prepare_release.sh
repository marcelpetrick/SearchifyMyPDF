#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# prepare_release.sh — collect the already built and tested artifacts into a release folder.
#
# Usage: scripts/prepare_release.sh VERSION OUT_DIR
#
# Copies dist/binary/searchify-pdf-VERSION-linux-x86_64 (+ inventory), the wheel and
# sdist from dist/, the GPL license, and writes SHA256SUMS and RELEASE_NOTES.md
# (commit, changelog entry, known limitations, source offer). Nothing is rebuilt here.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:?version}"
OUT="${2:?out dir}"
NAME="searchify-pdf-${VERSION}-linux-x86_64"
rm -rf "${OUT}" && mkdir -p "${OUT}"
cp "${ROOT_DIR}/dist/binary/${NAME}" "${OUT}/"
cp "${ROOT_DIR}/dist/binary/${NAME}.components.json" "${OUT}/"
cp "${ROOT_DIR}"/dist/searchify_pdf-"${VERSION}"*.whl "${OUT}/"
cp "${ROOT_DIR}"/dist/searchify_pdf-"${VERSION}".tar.gz "${OUT}/searchify_pdf-${VERSION}-source.tar.gz"
cp "${ROOT_DIR}/LICENSE" "${OUT}/LICENSE.txt"
COMMIT="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
{
    echo "# Searchify PDF ${VERSION}"
    echo
    echo "Built and tested from commit \`${COMMIT}\` by the release workflow (full \`localPipeline.sh\`:"
    echo "unit, integration with real OCR, UI, coverage gates, packaged E2E in clean offline containers)."
    echo
    echo "## Download"
    echo
    echo "- \`${NAME}\` — self-contained Linux x86-64 executable (glibc ≥ 2.35, e.g. Ubuntu 22.04+, Debian 12+, Fedora 36+)."
    echo "  \`chmod +x ${NAME} && ./${NAME}\` opens the window; \`./${NAME} --install-desktop-entry\` adds an app-menu launcher"
    echo "  that accepts dropped PDFs and folders. Settings are stored beside the executable."
    echo "- \`${NAME}.components.json\` — bundled component inventory (also shown under About in the app)."
    echo "- Wheel and source archive for Python users; \`docker pull ghcr.io/marcelpetrick/searchifymypdf:${VERSION}\` for the CLI image."
    echo
    echo "## Changes"
    echo
    sed -n "/^## ${VERSION} /,/^## /p" "${ROOT_DIR}/CHANGELOG.md" | sed '1d;$d'
    echo
    echo "## Known limitations"
    echo
    echo "- Linux x86-64 only. Windows and macOS builds are not produced or supported yet."
    echo "- Password-protected, encrypted and digitally signed PDFs are rejected (originals untouched)."
    echo "- Pages mixing digital text with scanned regions keep their existing text unchanged in 'keep existing text' mode."
    echo "- Bundled OCR languages: English and German. Handwriting and poor scans are not guaranteed."
    echo "- Dropping onto the raw executable depends on the file manager; use the installed launcher or the window."
    echo
    echo "## License and source"
    echo
    echo "GPL-3.0-or-later. The complete corresponding source is the tagged commit and the attached source archive."
    echo "Bundled third-party components and their licenses are listed in the inventory; Debian source packages for the"
    echo "bundled native libraries are available from the Ubuntu 22.04 archive (\`apt-get source <package>\`)."
} > "${OUT}/RELEASE_NOTES.md"
(cd "${OUT}" && sha256sum -- * > SHA256SUMS)
ls -la "${OUT}"
