#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Summarize ``mutmut results --all true`` output and enforce a minimum score.

Usage::

    scripts/mutation_score.py reports/mutation.txt --min 90

Each result line looks like ``    module.x_function__mutmut_3: survived``. The score is
``killed / (killed + survived)``; timeouts count as killed, "no tests" as survived.
Mutants listed in ``docs/mutation-equivalent.txt`` (one name per line) are reviewed
equivalent mutants and excluded from the denominator.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KILLED = {"killed", "timeout"}
SURVIVED = {"survived", "no tests"}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path)
    parser.add_argument("--min", type=float, default=90.0)
    args = parser.parse_args(argv)
    equivalent_file = ROOT / "docs" / "mutation-equivalent.txt"
    equivalent = set()
    if equivalent_file.exists():
        equivalent = {
            line.strip()
            for line in equivalent_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
    counts: collections.Counter[str] = collections.Counter()
    survivors = []
    for line in args.results.read_text(encoding="utf-8").splitlines():
        name, sep, status = line.strip().rpartition(": ")
        if not sep or "__mutmut_" not in name:
            continue
        if name in equivalent:
            counts["equivalent"] += 1
            continue
        counts[status] += 1
        if status in SURVIVED:
            survivors.append(name)
    killed = sum(counts[s] for s in KILLED)
    survived = sum(counts[s] for s in SURVIVED)
    total = killed + survived
    score = 100.0 * killed / total if total else 0.0
    print(f"mutants: {dict(counts)}")
    print(f"mutation score: {score:.1f}% ({killed}/{total}), minimum {args.min}%")
    for name in survivors:
        print(f"  survived: {name}")
    if total == 0:
        print("FAIL: no mutants were evaluated")
        return 1
    return 0 if score >= args.min else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
