#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# build_in_container.sh — runs inside packaging/linux/Dockerfile.build.
# Expects the repository read-only at /src and writes the executable, its SHA-256
# checksum and the component inventory to /out. Never modifies /src.
set -euo pipefail

rm -rf /work/repo && mkdir -p /work/repo
tar -C /src --exclude=.venv --exclude=.cache --exclude=dist --exclude=build \
    --exclude=reports --exclude=.git -cf - . | tar -C /work/repo -xf -
cd /work/repo
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/searchify_pdf/_version.py)"
NAME="searchify-pdf-${VERSION}-linux-x86_64"

# Runtime + GUI + PyInstaller only (no dev group): test/lint tools must not be bundled.
uv sync --locked --python 3.12 --quiet --no-dev --group build --extra gui
TESSDATA=/work/tessdata
if [[ -d /tessdata-cache ]]; then cp -r /tessdata-cache "${TESSDATA}"; fi
scripts/fetch_tessdata.sh "${TESSDATA}"
rm -f "${TESSDATA}"/*.part

mkdir -p /work/meta
uv run --no-sync python scripts/generate_inventory.py \
    --tessdata "${TESSDATA}" --out /work/meta/components.json --licenses-dir /work/meta/licenses

SEARCHIFY_BINARY_NAME="${NAME}" SEARCHIFY_TESSDATA="${TESSDATA}" \
SEARCHIFY_INVENTORY=/work/meta/components.json SEARCHIFY_LICENSES=/work/meta/licenses \
SEARCHIFY_ICU_DATA=/opt/icu-data/libicudata.so.73 \
    uv run --no-sync pyinstaller --noconfirm --clean --log-level WARN \
    --distpath /work/dist --workpath /work/build packaging/linux/searchify-pdf.spec

mkdir -p /out
cp "/work/dist/${NAME}" "/out/${NAME}"
cp /work/meta/components.json "/out/${NAME}.components.json"
(cd /out && sha256sum "${NAME}" > "${NAME}.sha256")
chown -R "${HOST_UID:-0}:${HOST_GID:-0}" /out
ls -la /out
