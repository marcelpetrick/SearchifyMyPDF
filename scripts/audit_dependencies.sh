#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# audit_dependencies.sh — scan the locked runtime dependencies for known vulnerabilities.
#
# Usage: scripts/audit_dependencies.sh
#
# Exports the runtime requirements (with hashes) from uv.lock and runs pip-audit 2.10.1
# against the PyPI advisory database. Exit code is non-zero when a vulnerability is found.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQ="$(mktemp)"
trap 'rm -f "${REQ}"' EXIT
uv export --project "${ROOT_DIR}" --locked --no-dev --no-emit-project --extra gui \
    --format requirements-txt -o "${REQ}" >/dev/null
uvx --from pip-audit==2.10.1 pip-audit --require-hashes --disable-pip -r "${REQ}"
