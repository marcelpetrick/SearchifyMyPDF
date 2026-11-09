#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# commit.sh — bump version, run the gate, commit atomically and push.
#
# Usage: scripts/commit.sh <patch|minor|major> "<type>(scope): message" [pipeline options]
#
# 1. Bumps the version and inserts a CHANGELOG entry (scripts/bump_version.py).
# 2. Runs ./localPipeline.sh with the given options (default: full pipeline).
# 3. On success: stages everything, commits with the message, pushes to origin/main.
#    On failure: reverts the version/CHANGELOG bump and exits non-zero (nothing committed).
#
# The message must follow Conventional Commits; it is validated with a regex.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"
PART="${1:?usage: commit.sh <patch|minor|major> \"message\" [pipeline options]}"
MESSAGE="${2:?missing commit message}"
shift 2

if ! [[ "${MESSAGE}" =~ ^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([a-z0-9-]+\))?!?:\ .+ ]]; then
    echo "not a Conventional Commit message: ${MESSAGE}" >&2
    exit 2
fi

cp src/searchify_pdf/_version.py /tmp/.searchify_version.bak.$$
cp CHANGELOG.md /tmp/.searchify_changelog.bak.$$
VERSION="$(uv run --no-sync python scripts/bump_version.py "${PART}" "${MESSAGE}")"
echo "version -> ${VERSION}"

if ! ./localPipeline.sh "$@"; then
    cp /tmp/.searchify_version.bak.$$ src/searchify_pdf/_version.py
    cp /tmp/.searchify_changelog.bak.$$ CHANGELOG.md
    rm -f /tmp/.searchify_*.bak.$$
    echo "pipeline failed — version bump reverted, nothing committed" >&2
    exit 1
fi
rm -f /tmp/.searchify_*.bak.$$

git add -A
git commit -q -m "${MESSAGE}" -m "Version: ${VERSION}"
git push -q origin main
echo "committed and pushed ${VERSION}: ${MESSAGE}"
