#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# docker_smoke.sh — build the CLI Docker image and prove it works.
#
# Usage: scripts/docker_smoke.sh [IMAGE_TAG]   (default: searchify-pdf:local)
#
# Builds ./Dockerfile, then runs the image offline (--network none) as an unprivileged
# user against a synthetic nested folder and checks: exit code, the adjacent
# *_searchable.pdf copy, recognized words in it, and that the original is unchanged.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${1:-searchify-pdf:local}"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "${ROOT_DIR}/src/searchify_pdf/_version.py")"
docker build -q --build-arg VERSION="${VERSION}" -t "${TAG}" "${ROOT_DIR}" >/dev/null
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
mkdir -p "${WORK}/data/Ordner mit Ä"
cd "${ROOT_DIR}"
uv run --no-sync python -c "
from pathlib import Path; from tests import synthetic
synthetic.scanned_pdf(Path('${WORK}/data/Ordner mit Ä/scan.pdf'))"
chmod -R a+rwX "${WORK}/data"
BEFORE="$(sha256sum "${WORK}/data/Ordner mit Ä/scan.pdf" | cut -d' ' -f1)"
docker run --rm "${TAG}" --version | grep -q "${VERSION}"
docker run --rm --network none -v "${WORK}/data:/data" "${TAG}" /data
OUT="${WORK}/data/Ordner mit Ä/scan_searchable.pdf"
test -f "${OUT}"
AFTER="$(sha256sum "${WORK}/data/Ordner mit Ä/scan.pdf" | cut -d' ' -f1)"
test "${BEFORE}" = "${AFTER}"
uv run --no-sync python -c "
from pathlib import Path; from tests.textutil import all_text, contains_words
assert contains_words(all_text(Path('${OUT}')), ['Searchable', 'invoice']), 'OCR text missing'"
set +e
docker run --rm --network none -v "${WORK}/data:/data" "${TAG}" /data >/dev/null
CODE=$?
set -e
test "${CODE}" -eq 3   # existing copy + default 'Ask me' policy → needs a decision
echo "docker image ${TAG} OK (version ${VERSION})"
