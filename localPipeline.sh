#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# localPipeline.sh — the single quality gate for Searchify PDF.
#
# GitHub Actions call this same script, so a local pass predicts a CI pass.
#
# Usage: ./localPipeline.sh [options]
#   --fast          only sync, format, lint, types and unit tests (no OCR/UI/package)
#   --no-package    skip the PyInstaller binary build and packaged E2E test
#   --no-docker     skip the Docker image build and smoke test
#   --mutation      additionally run the mutation-testing baseline (slow)
#   -h, --help      show this help
#
# Stages (each prints PASS/FAIL; the script exits non-zero if any stage fails):
#   1. sync        uv sync --locked (exact dependency lock)
#   2. tessdata    fetch pinned eng/deu/osd language data (scripts/fetch_tessdata.sh)
#   3. format      black --check
#   4. lint        ruff check
#   5. types       mypy --strict
#   6. headers     SPDX/copyright header check (scripts/check_headers.py)
#   7. tests       pytest unit + integration (real OCR) + UI (offscreen) with coverage
#   8. coverage    statement AND branch coverage >= 95% (scripts/check_coverage.py)
#   9. wheel       build sdist + wheel
#  10. binary      PyInstaller one-file Linux executable (scripts/build_linux_binary.sh)
#  11. e2e         run the packaged binary in a clean container (scripts/e2e_packaged.sh)
#  12. docker      build the CLI image and smoke-test it (scripts/docker_smoke.sh)
#  13. mutation    mutmut baseline (only with --mutation)
#
# Reports land in reports/ (coverage HTML/JSON, junit XML, logs).
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"
REPORTS="${ROOT_DIR}/reports"
FAST=false
PACKAGE=true
DOCKER=true
MUTATION=false

usage() { sed -n '5,30p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fast) FAST=true; PACKAGE=false; DOCKER=false ;;
        --no-package) PACKAGE=false ;;
        --no-docker) DOCKER=false ;;
        --mutation) MUTATION=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage; exit 2 ;;
    esac
    shift
done

mkdir -p "${REPORTS}"
declare -a SUMMARY=()
FAILED=0

stage() {
    local name="$1"; shift
    local log="${REPORTS}/${name}.log"
    local start=${SECONDS}
    printf '\n=== %s ===\n' "${name}"
    if "$@" 2>&1 | tee "${log}"; then
        SUMMARY+=("PASS  ${name} ($((SECONDS - start))s)")
    else
        SUMMARY+=("FAIL  ${name} ($((SECONDS - start))s) — see ${log}")
        FAILED=1
    fi
}

skip() { SUMMARY+=("SKIP  $1"); }

export TESSDATA_PREFIX="${ROOT_DIR}/.cache/tessdata"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
RUN="uv run --locked --no-sync"

stage sync uv sync --locked
stage tessdata scripts/fetch_tessdata.sh "${TESSDATA_PREFIX}"
stage format ${RUN} black --check src tests scripts
stage lint ${RUN} ruff check src tests scripts
stage types ${RUN} mypy
stage headers ${RUN} python scripts/check_headers.py

run_tests() {
    rm -f .coverage .coverage.* coverage.json
    local selection=()
    if ${FAST}; then selection=(tests/unit); fi
    ${RUN} coverage run -m pytest -m "not e2e" --junitxml="${REPORTS}/junit.xml" "${selection[@]}" \
        && ${RUN} coverage combine -q \
        && ${RUN} coverage report \
        && ${RUN} coverage json -q -o coverage.json \
        && ${RUN} coverage html -q -d "${REPORTS}/htmlcov"
}
stage tests run_tests
if ${FAST}; then
    skip "coverage (fast mode measures unit tests only)"
else
    stage coverage ${RUN} python scripts/check_coverage.py --json coverage.json --min 95 --target 98
fi

if ${FAST}; then
    skip wheel
else
    stage wheel bash -c "rm -rf dist && uv build --out-dir dist"
fi

# STAGES_PACKAGE_DOCKER_MUTATION (added as the packaging work lands)

printf '\n=== summary ===\n'
printf '%s\n' "${SUMMARY[@]}"
if [[ ${FAILED} -ne 0 ]]; then
    echo "PIPELINE FAILED"
    exit 1
fi
echo "PIPELINE GREEN"
