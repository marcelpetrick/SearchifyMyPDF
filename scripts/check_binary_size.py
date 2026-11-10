#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Report what a PyInstaller one-file executable contains and enforce a size budget.

Usage::

    scripts/check_binary_size.py BINARY [--budget-mb N] [--top N]

Prints the file size, the packed/unpacked totals, the largest entries and a per-package
breakdown (from PyInstaller's own archive reader), then exits 1 when the file exceeds
the budget. Used by ``localPipeline.sh`` after the binary stage so size cannot regress
unnoticed (PLAN step 29).
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

DEFAULT_BUDGET_MB = 95.0  # 0.17.2: 90.8 MB (was 133.6 MB before PLAN M2b)


def group_of(name: str) -> str:
    if name.startswith("PySide6/Qt/"):
        return "/".join(name.split("/")[:4])
    if "/" in name:
        return name.split("/")[0]
    return "(top-level native libraries)" if ".so" in name else name


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("binary", type=Path)
    parser.add_argument("--budget-mb", type=float, default=DEFAULT_BUDGET_MB)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args(argv)

    if not args.binary.is_file():
        print(f"FAIL: no executable at {args.binary}")
        return 1
    from PyInstaller.archive.readers import CArchiveReader

    size_mb = args.binary.stat().st_size / 1e6
    entries = [
        (packed, unpacked, name)
        for name, (_off, packed, unpacked, _flag, _typ) in CArchiveReader(
            str(args.binary)
        ).toc.items()
    ]
    entries.sort(reverse=True)
    packed_total = sum(e[0] for e in entries) / 1e6
    unpacked_total = sum(e[1] for e in entries) / 1e6
    print(f"{args.binary.name}: {size_mb:.1f} MB (budget {args.budget_mb:.0f} MB)")
    print(f"{len(entries)} entries, {packed_total:.1f} MB packed, {unpacked_total:.1f} MB unpacked")
    print("largest entries (packed MB):")
    for packed, _unpacked, name in entries[: args.top]:
        print(f"  {packed / 1e6:6.2f}  {name}")
    groups: collections.Counter[str] = collections.Counter()
    for packed, _unpacked, name in entries:
        groups[group_of(name)] += packed
    print("largest groups (packed MB):")
    for name, packed in groups.most_common(args.top):
        print(f"  {packed / 1e6:6.2f}  {name}")
    if size_mb > args.budget_mb:
        print(f"FAIL: {size_mb:.1f} MB exceeds the budget of {args.budget_mb:.0f} MB")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
