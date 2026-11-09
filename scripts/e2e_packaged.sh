#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# e2e_packaged.sh — run the packaged end-to-end tests against the built executable.
#
# Usage: scripts/e2e_packaged.sh [BINARY]   (default: newest dist/binary/searchify-pdf-*-linux-x86_64)
#
# Builds the small desktop-libraries test image (packaging/e2e/Dockerfile.desktop), then
# runs tests/e2e with pytest. The executable runs inside clean Ubuntu 22.04 containers
# without Python, Tesseract or network access. Fails if no binary exists.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BINARY="${1:-$(ls -t "${ROOT_DIR}"/dist/binary/searchify-pdf-*-linux-x86_64 2>/dev/null | head -1)}"
if [[ -z "${BINARY}" || ! -x "${BINARY}" ]]; then
    echo "no packaged binary found; run scripts/build_linux_binary.sh first" >&2
    exit 1
fi
docker build -q -t searchify-pdf-e2e-desktop:local -f "${ROOT_DIR}/packaging/e2e/Dockerfile.desktop" "${ROOT_DIR}/packaging/e2e" >/dev/null
cd "${ROOT_DIR}"
SEARCHIFY_E2E_BINARY="${BINARY}" uv run --locked --no-sync pytest -m e2e tests/e2e -v -p no:cacheprovider \
    --junitxml="${ROOT_DIR}/reports/junit-e2e.xml"
