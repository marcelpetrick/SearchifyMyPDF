#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# build_icu_data.sh — build a trimmed ICU data library for the bundled Qt (PLAN step 28).
#
# Usage: build_icu_data.sh SOURCE_DIR OUT_DIR   (run inside packaging/linux/Dockerfile.build)
#
# Qt (PySide6) links ICU 73.2; its libicudata.so.73 holds the Unicode/CLDR data for every
# language (32 MB, 12 MB packed). The UI is English/German only, so this rebuilds the
# *same* ICU version's data with icu-data-filter.json: locale-specific data for en/de
# (plus root, which still sorts and segments every script), no transliteration, no legacy
# charset tables, no CJK/Thai dictionaries, no character names. Only the data library is
# replaced; Qt's own libicuuc/libicui18n stay untouched. Inputs are checksum-verified.
set -euo pipefail
SRC="${1:?source dir with icu4c-73_2-src.tgz and icu4c-73_2-data.zip}"
OUT="${2:?output dir}"
FILTER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/icu-data-filter.json"
cd "${SRC}"
sha256sum -c - <<'SUMS'
818a80712ed3caacd9b652305e01afc7fa167e6f2e94996da44b90c2ab604ce1  icu4c-73_2-src.tgz
ca1ee076163b438461e484421a7679fc33a64cd0a54f9d4b401893fa1eb42701  icu4c-73_2-data.zip
SUMS
rm -rf icu && tar -xzf icu4c-73_2-src.tgz
rm -rf icu/source/data && unzip -q icu4c-73_2-data.zip -d icu/source
cd icu/source
ICU_DATA_FILTER_FILE="${FILTER}" ./configure --disable-samples --disable-tests \
    --disable-extras --disable-icuio --disable-layoutex --with-data-packaging=library \
    >/dev/null
make -j"$(nproc)" >/dev/null
mkdir -p "${OUT}"
cp lib/libicudata.so.73.2 "${OUT}/libicudata.so.73"
strip --strip-unneeded "${OUT}/libicudata.so.73"
cp ../LICENSE "${OUT}/LICENSE"
echo "73.2" > "${OUT}/VERSION"
ls -la "${OUT}/libicudata.so.73"
