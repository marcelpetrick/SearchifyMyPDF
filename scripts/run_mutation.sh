#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# run_mutation.sh — run mutmut on the core modules and enforce the agreed baseline.
#
# Usage: scripts/run_mutation.sh [--min-score PERCENT]   (default: the baseline in
#        docs/mutation-baseline.md, MIN_SCORE below)
#
# Targets and exclusions are configured in [tool.mutmut] (pyproject.toml). Writes the
# full result list to reports/mutation.txt and fails when the killed share of
# non-equivalent mutants drops below the threshold.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"
MIN_SCORE="${MIN_SCORE:-95}"
if [[ "${1:-}" == "--min-score" ]]; then MIN_SCORE="$2"; fi
export TESSDATA_PREFIX="${TESSDATA_PREFIX:-${ROOT_DIR}/.cache/tessdata}"
mkdir -p reports
rm -rf mutants
uv run --locked --no-sync mutmut run --max-children "$(nproc)" >/dev/null 2>&1 || true
uv run --locked --no-sync mutmut results --all true > reports/mutation.txt 2>&1 || true
uv run --locked --no-sync python scripts/mutation_score.py reports/mutation.txt --min "${MIN_SCORE}"
