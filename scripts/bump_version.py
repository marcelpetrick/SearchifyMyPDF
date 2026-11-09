#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Bump the SemVer version and add a CHANGELOG heading.

Usage::

    scripts/bump_version.py patch "fix: describe the change"
    scripts/bump_version.py minor "feat: describe the feature"
    scripts/bump_version.py --show

The version lives only in ``src/searchify_pdf/_version.py``. The changelog entry is
inserted directly under the ``## Unreleased``-free top of ``CHANGELOG.md`` as
``## <version> — <date>`` followed by ``- <message>``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "src" / "searchify_pdf" / "_version.py"
CHANGELOG = ROOT / "CHANGELOG.md"
PATTERN = re.compile(r'__version__ = "(\d+)\.(\d+)\.(\d+)"')
MARKER = "<!-- entries -->"


def read_version() -> tuple[int, int, int]:
    match = PATTERN.search(VERSION_FILE.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"no version found in {VERSION_FILE}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def bumped(version: tuple[int, int, int], part: str) -> tuple[int, int, int]:
    major, minor, patch = version
    if part == "major":
        return major + 1, 0, 0
    if part == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("part", nargs="?", choices=["major", "minor", "patch"])
    parser.add_argument("message", nargs="?", default="")
    parser.add_argument("--show", action="store_true", help="print the current version")
    args = parser.parse_args(argv)
    current = read_version()
    if args.show or args.part is None:
        print(".".join(map(str, current)))
        return 0
    new = ".".join(map(str, bumped(current, args.part)))
    text = VERSION_FILE.read_text(encoding="utf-8")
    VERSION_FILE.write_text(PATTERN.sub(f'__version__ = "{new}"', text), encoding="utf-8")
    if args.message:
        log = CHANGELOG.read_text(encoding="utf-8")
        entry = f"{MARKER}\n\n## {new} — {dt.date.today().isoformat()}\n\n- {args.message}"
        CHANGELOG.write_text(log.replace(MARKER, entry, 1), encoding="utf-8")
    print(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
