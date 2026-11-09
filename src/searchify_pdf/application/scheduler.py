# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Worker-count decisions and the shared CPU budget (VISION §7).

Document workers, OCRmyPDF page workers and Tesseract threads share one budget:
``documents x page_jobs <= cpu_count`` and Tesseract runs single-threaded
(``OMP_THREAD_LIMIT=1``), so nested parallelism never multiplies CPU use.
"""

from __future__ import annotations

import dataclasses
import os

import psutil

from searchify_pdf.domain.settings import MAX_FIXED_WORKERS, Settings, WorkerMode

AUTO_MAX_WORKERS = 8
MEMORY_PER_DOCUMENT = 768 * 1024 * 1024  # conservative peak per OCRmyPDF document


@dataclasses.dataclass(frozen=True, slots=True)
class WorkerPlan:
    documents: int
    page_jobs: int
    mode: WorkerMode


def system_resources() -> tuple[int, int]:
    """(logical CPUs, available memory in bytes)."""
    return os.cpu_count() or 1, int(psutil.virtual_memory().available)


def auto_documents(cpu_count: int, available_memory: int) -> int:
    """Conservative estimate: half the CPUs, bounded by memory and a hard cap."""
    by_cpu = max(1, cpu_count // 2)
    by_memory = max(1, available_memory // MEMORY_PER_DOCUMENT)
    return max(1, min(by_cpu, by_memory, AUTO_MAX_WORKERS))


def plan_workers(
    settings: Settings,
    pending: int,
    *,
    cpu_count: int,
    available_memory: int,
) -> WorkerPlan:
    cpu_count = max(1, cpu_count)
    if settings.worker_mode is WorkerMode.SEQUENTIAL:
        documents = 1
    elif settings.worker_mode is WorkerMode.FIXED:
        documents = min(settings.fixed_workers, MAX_FIXED_WORKERS)
    else:
        documents = auto_documents(cpu_count, available_memory)
    documents = max(1, min(documents, max(1, pending)))
    page_jobs = max(1, cpu_count // documents)
    return WorkerPlan(documents, page_jobs, settings.worker_mode)
