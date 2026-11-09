#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Verify that every first-party source file carries the GPL SPDX + copyright header.

Usage::

    scripts/check_headers.py            # check src/, tests/, scripts/, localPipeline.sh

Checks ``*.py`` and ``*.sh`` files (empty ``__init__.py`` files are exempt). The header
must appear within the first five lines. Exit code 1 lists the offending files.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPDX = "SPDX-License-Identifier: GPL-3.0-or-later"
COPYRIGHT = "Copyright (C) 2026 Marcel Petrick"


def candidates() -> list[Path]:
    files = [ROOT / "localPipeline.sh"]
    for folder in ("src", "tests", "scripts", "packaging"):
        base = ROOT / folder
        if base.exists():
            files.extend(p for p in base.rglob("*") if p.suffix in {".py", ".sh"})
    return sorted(p for p in files if p.exists() and p.stat().st_size > 0)


def main() -> int:
    missing = []
    for path in candidates():
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:5])
        if SPDX not in head or COPYRIGHT not in head:
            missing.append(path.relative_to(ROOT))
    for path in missing:
        print(f"missing license header: {path}")
    print(f"checked {len(candidates())} files, {len(missing)} missing headers")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
