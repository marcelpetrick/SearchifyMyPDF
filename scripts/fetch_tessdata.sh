#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# fetch_tessdata.sh — download the pinned Tesseract language data into a folder.
#
# Usage: scripts/fetch_tessdata.sh [TARGET_DIR]   (default: .cache/tessdata)
#
# Downloads tessdata_fast 4.1.0 (Apache-2.0) eng, deu and osd models, verifies
# their SHA-256 checksums and copies Tesseract's "configs" directory (needed for
# the hocr/txt output configs that OCRmyPDF uses). Idempotent: verified files are
# not downloaded again. Point TESSDATA_PREFIX at TARGET_DIR afterwards.
set -euo pipefail

TARGET="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.cache/tessdata}"
BASE_URL="https://github.com/tesseract-ocr/tessdata_fast/raw/4.1.0"
declare -A SHA=(
    [eng]=7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2
    [deu]=19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d
    [osd]=9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff
)

mkdir -p "${TARGET}/configs"
for lang in eng deu osd; do
    file="${TARGET}/${lang}.traineddata"
    if [[ -f "${file}" ]] && echo "${SHA[$lang]}  ${file}" | sha256sum -c --quiet - 2>/dev/null; then
        continue
    fi
    curl -fsSL --retry 3 -o "${file}.part" "${BASE_URL}/${lang}.traineddata"
    echo "${SHA[$lang]}  ${file}.part" | sha256sum -c --quiet -
    mv "${file}.part" "${file}"
done

# Minimal Tesseract output configs used by OCRmyPDF (identical to upstream tessdata/configs).
printf 'tessedit_create_hocr 1\nhocr_font_info 0\n' > "${TARGET}/configs/hocr"
printf 'tessedit_create_txt 1\n' > "${TARGET}/configs/txt"
printf 'tessedit_create_pdf 1\n' > "${TARGET}/configs/pdf"
printf 'tessedit_create_alto 1\n' > "${TARGET}/configs/alto"
echo "tessdata ready in ${TARGET}"
