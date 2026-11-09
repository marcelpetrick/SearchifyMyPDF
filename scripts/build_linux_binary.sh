#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# build_linux_binary.sh — build the self-contained Linux x86-64 executable.
#
# Usage: scripts/build_linux_binary.sh [OUT_DIR]   (default: dist/binary)
#
# Builds packaging/linux/Dockerfile.build (Ubuntu 22.04, glibc 2.35 baseline) and runs
# PyInstaller inside it. The result bundles Python, Qt, OCRmyPDF, Tesseract with its
# libraries, and the eng/deu/osd language data. Output files:
#   searchify-pdf-<version>-linux-x86_64              the executable
#   searchify-pdf-<version>-linux-x86_64.sha256       checksum
#   searchify-pdf-<version>-linux-x86_64.components.json   component inventory
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-${ROOT_DIR}/dist/binary}"
IMAGE="searchify-pdf-builder:local"
mkdir -p "${OUT_DIR}" "${ROOT_DIR}/.cache/tessdata"
rm -f "${OUT_DIR}"/searchify-pdf-*

docker build -q -t "${IMAGE}" -f "${ROOT_DIR}/packaging/linux/Dockerfile.build" "${ROOT_DIR}/packaging/linux" >/dev/null
docker run --rm \
    -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
    -v "${ROOT_DIR}:/src:ro" \
    -v "${ROOT_DIR}/.cache/tessdata:/tessdata-cache:ro" \
    -v "${OUT_DIR}:/out" \
    -v searchify-pdf-uv-cache:/root/.cache/uv \
    "${IMAGE}" bash /src/packaging/linux/build_in_container.sh
ls -la "${OUT_DIR}"
