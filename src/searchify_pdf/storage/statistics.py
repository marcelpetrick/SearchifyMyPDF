# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Optional, local-only usage statistics (VISION §8).

* Disabled by default; nothing is written unless the user enables it.
* Stored beside the application in ``searchify-pdf.statistics.json`` (versioned JSON).
* No recognized text and no paths are stored — only counts, configured languages and
  durations.
* Every batch is recorded exactly once (by batch id), so retries/re-renders cannot
  double count. Failed, cancelled, skipped and action-required jobs are counted in the
  outcome counters but excluded from timing distributions.
* Raw samples are retained (up to :data:`MAX_SAMPLES`, oldest dropped) so medians are
  true medians, never medians of batch averages.
* OCRmyPDF does not expose per-page timings. The per-page figure is an explicitly
  labelled *estimate* (document duration ÷ OCR-processed pages); it is never shown as
  a measured value. Parallel page work means such sums can exceed wall time.
* Language detection is not performed; detected language is reported as "not measured".
"""

from __future__ import annotations

import dataclasses
import json
import statistics as pystats
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from searchify_pdf.domain.jobs import BatchSummary, Outcome
from searchify_pdf.storage.atomic import atomic_write_bytes, classify_os_error

STATS_FILE_NAME = "searchify-pdf.statistics.json"
SCHEMA_VERSION = 1
MAX_SAMPLES = 100_000
MAX_BATCH_IDS = 1000
PAGE_FIELDS = ("inspected", "ocr_processed", "preserved", "skipped", "failed")
TIMED_OUTCOMES = {Outcome.CONVERTED, Outcome.PRESERVED}


class StatisticsError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclasses.dataclass(frozen=True, slots=True)
class Distribution:
    count: int
    total: float
    mean: float
    median: float


def describe(values: Sequence[float]) -> Distribution | None:
    if not values:
        return None
    total = float(sum(values))
    return Distribution(len(values), total, total / len(values), float(pystats.median(values)))


@dataclasses.dataclass(frozen=True, slots=True)
class Statistics:
    attempted: int = 0
    outcomes: dict[str, int] = dataclasses.field(default_factory=dict)
    pages: dict[str, int] = dataclasses.field(default_factory=dict)
    languages: dict[str, int] = dataclasses.field(default_factory=dict)
    document_seconds: tuple[float, ...] = ()
    page_estimate_seconds: tuple[float, ...] = ()
    queue_seconds: tuple[float, ...] = ()
    batch_wall_seconds: tuple[float, ...] = ()
    batch_ids: tuple[str, ...] = ()

    @property
    def processed(self) -> int:
        """Documents that produced a copy (converted + preserved)."""
        return self.outcomes.get(Outcome.CONVERTED.value, 0) + self.outcomes.get(
            Outcome.PRESERVED.value, 0
        )

    def to_json(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["schema_version"] = SCHEMA_VERSION
        for key in ("document_seconds", "page_estimate_seconds", "queue_seconds"):
            data[key] = [round(v, 4) for v in data[key]]
        data["batch_wall_seconds"] = [round(v, 4) for v in data["batch_wall_seconds"]]
        data["batch_ids"] = list(data["batch_ids"])
        return data

    @classmethod
    def from_json(cls, data: object) -> Statistics:
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise StatisticsError("schema_invalid")
        try:
            return cls(
                attempted=int(data.get("attempted", 0)),
                outcomes={str(k): int(v) for k, v in dict(data.get("outcomes", {})).items()},
                pages={str(k): int(v) for k, v in dict(data.get("pages", {})).items()},
                languages={str(k): int(v) for k, v in dict(data.get("languages", {})).items()},
                document_seconds=tuple(float(v) for v in data.get("document_seconds", [])),
                page_estimate_seconds=tuple(
                    float(v) for v in data.get("page_estimate_seconds", [])
                ),
                queue_seconds=tuple(float(v) for v in data.get("queue_seconds", [])),
                batch_wall_seconds=tuple(float(v) for v in data.get("batch_wall_seconds", [])),
                batch_ids=tuple(str(v) for v in data.get("batch_ids", [])),
            )
        except (TypeError, ValueError) as exc:
            raise StatisticsError("value_invalid", str(exc)) from exc


def _cap(values: Sequence[float]) -> tuple[float, ...]:
    return tuple(values[-MAX_SAMPLES:])


def record(
    stats: Statistics, summary: BatchSummary, languages: Sequence[str], batch_id: str
) -> Statistics:
    """Pure function: return ``stats`` with ``summary`` added (idempotent per batch id)."""
    if batch_id in stats.batch_ids or not summary.results:
        return stats
    outcomes = dict(stats.outcomes)
    pages = dict(stats.pages)
    langs = dict(stats.languages)
    docs, per_page, queues = (
        list(stats.document_seconds),
        list(stats.page_estimate_seconds),
        list(stats.queue_seconds),
    )
    for result in summary.results:
        outcomes[result.outcome.value] = outcomes.get(result.outcome.value, 0) + 1
        for field in PAGE_FIELDS:
            pages[field] = pages.get(field, 0) + int(getattr(result.pages, field))
        for lang in languages:
            langs[lang] = langs.get(lang, 0) + 1
        if result.outcome in TIMED_OUTCOMES:
            docs.append(result.duration_seconds)
            queues.append(result.queue_seconds)
            if result.outcome is Outcome.CONVERTED and result.pages.ocr_processed > 0:
                per_page.append(result.duration_seconds / result.pages.ocr_processed)
    return Statistics(
        attempted=stats.attempted + len(summary.results),
        outcomes=outcomes,
        pages=pages,
        languages=langs,
        document_seconds=_cap(docs),
        page_estimate_seconds=_cap(per_page),
        queue_seconds=_cap(queues),
        batch_wall_seconds=_cap([*stats.batch_wall_seconds, summary.wall_seconds]),
        batch_ids=(*stats.batch_ids, batch_id)[-MAX_BATCH_IDS:],
    )


class StatisticsRepository:
    def __init__(self, directory: Path) -> None:
        self.path = directory / STATS_FILE_NAME

    def load(self) -> Statistics:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return Statistics()
        except OSError as exc:
            raise StatisticsError(classify_os_error(exc), str(exc)) from exc
        try:
            return Statistics.from_json(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StatisticsError("json_invalid", str(exc)) from exc

    def save(self, stats: Statistics) -> None:
        try:
            atomic_write_bytes(self.path, json.dumps(stats.to_json()).encode())
        except OSError as exc:
            raise StatisticsError(classify_os_error(exc), str(exc)) from exc

    def reset(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise StatisticsError(classify_os_error(exc), str(exc)) from exc

    def record_batch(
        self, summary: BatchSummary, languages: Sequence[str], batch_id: str | None = None
    ) -> str:
        """Load, add and save; return an error code ("" on success). Never raises, so a
        statistics problem can never discard a successfully converted PDF."""
        try:
            stats = self.load()
        except StatisticsError as exc:
            if exc.code not in {"json_invalid", "schema_invalid", "value_invalid"}:
                return exc.code
            stats = Statistics()  # corrupt file: start fresh rather than fail the batch
        try:
            self.save(record(stats, summary, languages, batch_id or uuid.uuid4().hex))
        except StatisticsError as exc:
            return exc.code
        return ""
