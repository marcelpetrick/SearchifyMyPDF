#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Reproducible OCR benchmark: sequential vs parallel on a synthetic corpus.

Usage::

    scripts/benchmark.py [--documents 8] [--pages 3] [--dpi 200] [--out reports/benchmark.json]

Records platform, CPU count, engine versions, language data, corpus shape, worker plan,
wall-clock time, per-document mean/median and the peak resident memory of the process
tree, for the modes sequential, fixed=2 and auto. Use the JSON for baselines; compare
runs with tolerances, never exact timings (VISION §7).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from tests import synthetic  # noqa: E402

from searchify_pdf.application.workflow import BatchRunner  # noqa: E402
from searchify_pdf.domain.jobs import Outcome  # noqa: E402
from searchify_pdf.domain.settings import Settings, WorkerMode  # noqa: E402
from searchify_pdf.engines.ocrmypdf_engine import OcrmypdfEngine  # noqa: E402


class PeakMemory:
    def __init__(self) -> None:
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)

    def _poll(self) -> None:
        me = psutil.Process()
        while not self._stop.wait(0.1):
            total = 0
            for proc in [me, *me.children(recursive=True)]:
                with contextlib.suppress(psutil.Error):
                    total += proc.memory_info().rss
            self.peak = max(self.peak, total)

    def __enter__(self) -> PeakMemory:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()


def run_mode(corpus: Path, settings: Settings) -> dict[str, object]:
    for old in corpus.glob("*_searchable.pdf"):
        old.unlink()
    engine = OcrmypdfEngine()
    runner = BatchRunner(settings, engine, version="bench")
    with PeakMemory() as memory:
        start = time.monotonic()
        summary = runner.run([corpus])
        wall = time.monotonic() - start
    durations = [r.duration_seconds for r in summary.results if r.outcome is Outcome.CONVERTED]
    return {
        "mode": settings.worker_mode.value,
        "documents_at_once": summary.workers,
        "page_jobs": runner.plan.page_jobs if runner.plan else None,
        "converted": summary.count(Outcome.CONVERTED),
        "wall_seconds": round(wall, 2),
        "document_mean_seconds": round(statistics.mean(durations), 2) if durations else None,
        "document_median_seconds": round(statistics.median(durations), 2) if durations else None,
        "peak_rss_mib": round(memory.peak / 2**20, 1),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--documents", type=int, default=8)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--out", type=Path, default=ROOT / "reports" / "benchmark.json")
    args = parser.parse_args(argv)
    os.environ.setdefault("TESSDATA_PREFIX", str(ROOT / ".cache" / "tessdata"))
    engine = OcrmypdfEngine()
    caps = engine.capabilities()
    with tempfile.TemporaryDirectory() as tmp:
        corpus = Path(tmp)
        for i in range(args.documents):
            pages = [
                synthetic.ENGLISH_LINES if p % 2 == 0 else synthetic.GERMAN_LINES
                for p in range(args.pages)
            ]
            synthetic.scanned_pdf(corpus / f"doc{i:02d}.pdf", pages, dpi=args.dpi)
        modes = [
            Settings(worker_mode=WorkerMode.SEQUENTIAL),
            Settings(worker_mode=WorkerMode.FIXED, fixed_workers=2),
            Settings(worker_mode=WorkerMode.AUTO),
        ]
        results = [run_mode(corpus, s) for s in modes]
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "memory_gib": round(psutil.virtual_memory().total / 2**30, 1),
        "engine": caps.name,
        "languages": ["eng", "deu"],
        "language_data": "tessdata_fast 4.1.0",
        "corpus": {
            "documents": args.documents,
            "pages_per_document": args.pages,
            "dpi": args.dpi,
            "page_type": "synthetic A4 scan, 2 text lines",
        },
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
