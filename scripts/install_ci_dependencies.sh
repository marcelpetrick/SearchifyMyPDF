#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# install_ci_dependencies.sh — install the Debian/Ubuntu system packages the pipeline
# needs on a fresh runner: Tesseract (engine binary; language data is fetched and
# pinned separately by fetch_tessdata.sh) and the shared libraries Qt needs for the
# offscreen platform plugin used by UI tests.
#
# Usage: scripts/install_ci_dependencies.sh   (uses sudo when not root)
set -euo pipefail
SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then SUDO="sudo"; fi
${SUDO} apt-get update -qq
${SUDO} apt-get install -y -qq --no-install-recommends \
    tesseract-ocr \
    libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libglib2.0-0t64 \
    >/dev/null
tesseract --version | head -1
