#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# commit.sh — bump version, run the gate, commit atomically and push.
#
# Usage: scripts/commit.sh <patch|minor|major> "<type>(scope): message" [pipeline options]
#
# 1. Bumps the version, inserts a CHANGELOG entry (scripts/bump_version.py) and appends
#    the step to the progress log at the end of PLAN.md.
# 2. Runs ./localPipeline.sh with the given options (default: full pipeline).
# 3. On success: commits the staged changes (or everything when nothing is staged),
#    commits with the message, pushes to origin/main.
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
cp PLAN.md /tmp/.searchify_plan.bak.$$
printf '| %s | %s | %s |\n' "${VERSION}" "$(date +%F)" "${MESSAGE}" >> PLAN.md

if ! ./localPipeline.sh "$@"; then
    cp /tmp/.searchify_version.bak.$$ src/searchify_pdf/_version.py
    cp /tmp/.searchify_changelog.bak.$$ CHANGELOG.md
    cp /tmp/.searchify_plan.bak.$$ PLAN.md
    rm -f /tmp/.searchify_*.bak.$$
    echo "pipeline failed — version bump reverted, nothing committed" >&2
    exit 1
fi
rm -f /tmp/.searchify_*.bak.$$

# Atomic commits: when changes are already staged, commit only those (plus the version,
# changelog and plan files touched by this script); otherwise commit the whole tree.
if git diff --cached --quiet; then
    git add -A
else
    git add src/searchify_pdf/_version.py CHANGELOG.md PLAN.md
fi
git commit -q -m "${MESSAGE}" -m "Version: ${VERSION}"
git push -q origin main
echo "committed and pushed ${VERSION}: ${MESSAGE}"
