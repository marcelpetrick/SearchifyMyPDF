#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Enforce statement and branch coverage thresholds separately.

coverage.py only reports one combined percentage, which can hide weak branch
coverage behind strong statement coverage. This script reads ``coverage.json``
(produced by ``coverage json``) and checks both numbers independently.

Usage::

    scripts/check_coverage.py [--json coverage.json] [--min 95] [--target 98]

Exit code 0 when both metrics reach ``--min``; prints a warning (but passes)
when a metric is below ``--target``. Writes a one-line badge value to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def percentages(data: dict[str, object]) -> tuple[float, float]:
    totals = data["totals"]
    assert isinstance(totals, dict)
    statements = int(totals["num_statements"])
    covered_statements = int(totals["covered_lines"])
    branches = int(totals["num_branches"])
    covered_branches = int(totals["covered_branches"])
    statement_pct = 100.0 * covered_statements / statements if statements else 100.0
    branch_pct = 100.0 * covered_branches / branches if branches else 100.0
    return statement_pct, branch_pct


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check statement and branch coverage.")
    parser.add_argument("--json", type=Path, default=Path("coverage.json"))
    parser.add_argument("--min", type=float, default=95.0)
    parser.add_argument("--target", type=float, default=98.0)
    args = parser.parse_args(argv)
    statement_pct, branch_pct = percentages(json.loads(args.json.read_text(encoding="utf-8")))
    print(f"statement coverage: {statement_pct:.2f}%  branch coverage: {branch_pct:.2f}%")
    failed = False
    for name, value in (("statement", statement_pct), ("branch", branch_pct)):
        if value < args.min:
            print(f"FAIL: {name} coverage {value:.2f}% is below the minimum {args.min}%")
            failed = True
        elif value < args.target:
            print(f"WARN: {name} coverage {value:.2f}% is below the target {args.target}%")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
