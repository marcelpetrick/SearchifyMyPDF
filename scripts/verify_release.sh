#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# verify_release.sh — download a GitHub release and check what users will get.
#
# Usage: scripts/verify_release.sh TAG [WORK_DIR]   (needs gh with a token; GITHUB_REPOSITORY
#        or the current repository)
#
# Downloads every asset of TAG, checks SHA256SUMS, requires an executable for Linux,
# Windows and macOS, and runs the Linux executable's --version.
set -euo pipefail
TAG="${1:?tag}"
WORK="${2:-$(mktemp -d)}"
REPO="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
rm -rf "${WORK}" && mkdir -p "${WORK}" && cd "${WORK}"
gh release download "${TAG}" --repo "${REPO}"
ls -la
sha256sum -c SHA256SUMS
for platform in linux-x86_64 windows-x86_64.exe macos-arm64; do
    ls searchify-pdf-*-"${platform}" >/dev/null
done
chmod +x searchify-pdf-*-linux-x86_64
./searchify-pdf-*-linux-x86_64 --version
echo "release ${TAG}: all assets verified"
