#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# build_native_binary.sh — build and smoke-test the one-file executable on Windows or macOS.
#
# Usage: scripts/build_native_binary.sh [OUT_DIR]   (default: dist/binary)
#
# Runs on a GitHub-hosted windows/macos runner (Git Bash on Windows, bash ≥ 4 on macOS)
# after Tesseract was installed by the platform package manager (Chocolatey / Homebrew).
# Linux builds use packaging/linux/build_in_container.sh instead (glibc baseline).
#
# Steps: runtime-only uv sync → pinned tessdata → component inventory → PyInstaller
# (packaging/linux/searchify-pdf.spec, cross-platform) → smoke tests of the *built*
# executable with the system Tesseract hidden from PATH:
#   1. --version and --licenses,
#   2. the GUI (offscreen Qt platform) converts a dropped folder,
#   3. --cli converts a synthetic scan and the copy contains the expected words,
#   4. --check-text rates a correct OCR layer good and a garbled one poor (ADR 0013),
#   5. --store-settings-in-profile writes to this platform's profile folder and the
#      next run uses those settings (ADR 0012).
# Writes OUT_DIR/searchify-pdf-VERSION-<os>-<arch>[.exe] plus .components.json and .sha256.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"
OUT="${1:-dist/binary}"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/searchify_pdf/_version.py)"

case "$(uname -s)" in
    MINGW* | MSYS* | CYGWIN*)
        PLATFORM="windows-x86_64"
        EXT=".exe"
        TESSERACT="${SEARCHIFY_TESSERACT:-/c/Program Files/Tesseract-OCR/tesseract.exe}"
        TESSERACT_NATIVE="$(cygpath -w "${TESSERACT}")"
        ;;
    Darwin)
        PLATFORM="macos-$(uname -m)"
        EXT=""
        TESSERACT="${SEARCHIFY_TESSERACT:-$(command -v tesseract)}"
        TESSERACT_NATIVE="${TESSERACT}"
        ;;
    *)
        echo "use scripts/build_linux_binary.sh on Linux" >&2
        exit 2
        ;;
esac
NAME="searchify-pdf-${VERSION}-${PLATFORM}"
"${TESSERACT}" --version | head -2

WORK="${ROOT_DIR}/build/native"
rm -rf "${WORK}" && mkdir -p "${WORK}/meta" "${OUT}"
uv sync --locked --quiet --no-dev --group build --extra gui
scripts/fetch_tessdata.sh "${WORK}/tessdata"
rm -f "${WORK}"/tessdata/*.part

export SEARCHIFY_TESSERACT="${TESSERACT_NATIVE}"
uv run --no-sync python scripts/generate_inventory.py \
    --tessdata "${WORK}/tessdata" --out "${WORK}/meta/components.json" \
    --licenses-dir "${WORK}/meta/licenses"

SEARCHIFY_BINARY_NAME="${NAME}" SEARCHIFY_TESSDATA="${WORK}/tessdata" \
SEARCHIFY_INVENTORY="${WORK}/meta/components.json" SEARCHIFY_LICENSES="${WORK}/meta/licenses" \
    uv run --no-sync pyinstaller --noconfirm --clean --log-level WARN \
    --distpath "${WORK}/dist" --workpath "${WORK}/build" packaging/linux/searchify-pdf.spec

BINARY="${OUT}/${NAME}${EXT}"
cp "${WORK}/dist/${NAME}${EXT}" "${BINARY}"
cp "${WORK}/meta/components.json" "${OUT}/${NAME}${EXT}.components.json"
(cd "${OUT}" && sha256sum "${NAME}${EXT}" > "${NAME}${EXT}.sha256")
ls -la "${OUT}"

# --- smoke tests of the built executable ---------------------------------------------------
# Hide the system Tesseract so the bundled one must be used.
SMOKE_PATH="/usr/bin:/bin"
if [[ -n "${SYSTEMROOT:-}" ]]; then SMOKE_PATH="/usr/bin:/bin:$(cygpath -u "${SYSTEMROOT}")/System32"; fi
SMOKE="${WORK}/smoke"
mkdir -p "${SMOKE}/app" "${SMOKE}/docs"
cp "${BINARY}" "${SMOKE}/app/"
APP="${SMOKE}/app/${NAME}${EXT}"
PATH="${SMOKE_PATH}" "${APP}" --version | tee "${SMOKE}/version.txt"
grep -q "${VERSION}" "${SMOKE}/version.txt"
PATH="${SMOKE_PATH}" "${APP}" --licenses | grep -i "tesseract"
uv run --no-sync python -c "
import sys; sys.path.insert(0, '.')
from pathlib import Path
from tests import synthetic
synthetic.scanned_pdf(Path(sys.argv[1]))
" "${SMOKE}/docs/Invoice scan.pdf"
PATH="${SMOKE_PATH}" QT_QPA_PLATFORM=offscreen "${APP}" --gui-smoke-test "${SMOKE}/docs"
PATH="${SMOKE_PATH}" "${APP}" --cli --non-interactive --on-existing-output overwrite \
    "${SMOKE}/docs" | tee "${SMOKE}/cli.txt"
uv run --no-sync python -c "
import sys; sys.path.insert(0, '.')
from pathlib import Path
from tests.textutil import all_text, contains_words
text = all_text(Path(sys.argv[1]))
print(repr(text))
assert contains_words(text, ['Searchable', 'invoice', 'Payment', 'thirty']), text
" "${SMOKE}/docs/Invoice scan_searchable.pdf"

# 4. Existing-text cross-check with the bundled Tesseract.
mkdir -p "${SMOKE}/layers"
uv run --no-sync python -c "
import sys; sys.path.insert(0, '.')
from pathlib import Path
from tests import synthetic
folder = Path(sys.argv[1])
synthetic.ocr_layer_pdf(folder / 'good.pdf')
synthetic.ocr_layer_pdf(folder / 'garbled.pdf', layer_lines=synthetic.GARBLED_LINES)
" "${SMOKE}/layers"
PATH="${SMOKE_PATH}" "${APP}" --check-text "${SMOKE}/layers" | tee "${SMOKE}/check.txt"
grep "good.pdf" "${SMOKE}/check.txt" | grep -q "looks good"
grep "garbled.pdf" "${SMOKE}/check.txt" | grep -q "looks poor"
test "$(find "${SMOKE}/layers" -type f | wc -l)" -eq 2  # nothing written

# 5. Opt-in user-profile settings in the platform's real profile location.
if [[ "${PLATFORM}" == windows-* ]]; then
    PROFILE="${SMOKE}/appdata/Searchify PDF"
    PROFILE_ENV=(APPDATA="$(cygpath -w "${SMOKE}/appdata")")
else
    PROFILE="${SMOKE}/home/Library/Application Support/Searchify PDF"
    PROFILE_ENV=(HOME="${SMOKE}/home")
fi
mkdir -p "${SMOKE}/home" "${SMOKE}/appdata" "${SMOKE}/profiled"
env PATH="${SMOKE_PATH}" "${PROFILE_ENV[@]}" "${APP}" --store-settings-in-profile --suffix _ocr
grep -q '"output_suffix": "_ocr"' "${PROFILE}/searchify-pdf.settings.json"
test ! -e "${SMOKE}/app/searchify-pdf.settings.json"
cp "${SMOKE}/docs/Invoice scan.pdf" "${SMOKE}/profiled/scan.pdf"
env PATH="${SMOKE_PATH}" "${PROFILE_ENV[@]}" "${APP}" --cli --non-interactive "${SMOKE}/profiled"
test -f "${SMOKE}/profiled/scan_ocr.pdf"
echo "native build ${NAME}${EXT}: smoke tests passed"
