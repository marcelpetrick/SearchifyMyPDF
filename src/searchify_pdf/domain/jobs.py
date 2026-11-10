# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Job lifecycle, outcomes, events and batch summaries (VISION §9)."""

from __future__ import annotations

import dataclasses
import enum
from collections import Counter
from pathlib import Path


class JobState(enum.StrEnum):
    DISCOVERED = "discovered"
    DECIDING = "deciding"
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    PUBLISHING = "publishing"
    FINISHED = "finished"


class Outcome(enum.StrEnum):
    """Terminal outcomes reported separately in every summary (VISION §3.4)."""

    CONVERTED = "converted"
    PRESERVED = "preserved"  # all pages already had text; copy published unchanged
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ACTION_REQUIRED = "action_required"  # non-interactive Ask policy, nothing written


class Reason(enum.StrEnum):
    """Stable reason codes; translated by :mod:`searchify_pdf.i18n`."""

    OK = "ok"
    OUTPUT_EXISTS = "output_exists"
    USER_SKIPPED = "user_skipped"
    GENERATED_COPY = "generated_copy"
    LOOKS_GENERATED = "looks_generated"
    ENCRYPTED = "encrypted"
    PASSWORD_REQUIRED = "password_required"  # noqa: S105 - reason code, not a secret
    WRONG_PASSWORD = "wrong_password"  # noqa: S105 - reason code, not a secret
    RESTRICTED = "restricted"
    SIGNED = "signed"
    INVALID_PDF = "invalid_pdf"
    UNREADABLE = "unreadable"
    NOT_FOUND = "not_found"
    NOT_PDF = "not_pdf"
    SYMLINK = "symlink"
    DESTINATION_ALIAS = "destination_alias"
    DESTINATION_COLLISION = "destination_collision"
    DESTINATION_SYMLINK = "destination_symlink"
    LOCKED = "locked"
    ENGINE_FAILED = "engine_failed"
    ENGINE_MISSING = "engine_missing"
    TIMEOUT = "timeout"
    REDO_UNSUPPORTED = "redo_unsupported"
    VALIDATION_FAILED = "validation_failed"
    WRITE_FAILED = "write_failed"
    DISK_FULL = "disk_full"
    PERMISSION_DENIED = "permission_denied"
    CANCELLED = "cancelled"
    ASK_NONINTERACTIVE = "ask_noninteractive"
    ALL_PAGES_HAVE_TEXT = "all_pages_have_text"
    DESKEW_DISABLED_FOR_REDO = "deskew_disabled_for_redo"
    EXISTING_TEXT_DOUBTFUL = "existing_text_doubtful"  # kept text disagrees in part (#6)
    EXISTING_TEXT_POOR = "existing_text_poor"  # kept text mostly disagrees (#6)


@dataclasses.dataclass(frozen=True, slots=True)
class PageCounts:
    inspected: int = 0
    ocr_processed: int = 0
    preserved: int = 0
    skipped: int = 0
    failed: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class JobResult:
    job_id: int
    source: Path
    destination: Path | None
    outcome: Outcome
    reason: Reason
    detail: str = ""
    duration_seconds: float = 0.0
    queue_seconds: float = 0.0
    pages: PageCounts = PageCounts()
    notes: tuple[Reason, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class JobEvent:
    """Progress event emitted for UI/CLI/statistics; ``result`` is set when finished."""

    job_id: int
    source: Path
    state: JobState
    result: JobResult | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class Omission:
    """A path found during discovery that will not be processed, with the reason."""

    path: Path
    reason: Reason
    detail: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class BatchSummary:
    results: tuple[JobResult, ...]
    omissions: tuple[Omission, ...] = ()
    wall_seconds: float = 0.0
    workers: int = 1
    statistics_error: str = ""

    def count(self, outcome: Outcome) -> int:
        return sum(1 for result in self.results if result.outcome is outcome)

    @property
    def counts(self) -> dict[Outcome, int]:
        counter = Counter(result.outcome for result in self.results)
        return {outcome: counter.get(outcome, 0) for outcome in Outcome}

    @property
    def succeeded(self) -> bool:
        bad = {Outcome.FAILED, Outcome.CANCELLED, Outcome.ACTION_REQUIRED}
        return not any(result.outcome in bad for result in self.results)

    @property
    def folders(self) -> tuple[Path, ...]:
        """Distinct folders that received outputs (for an Open folder action)."""
        seen: dict[Path, None] = {}
        for result in self.results:
            if result.destination is not None and result.outcome in {
                Outcome.CONVERTED,
                Outcome.PRESERVED,
            }:
                seen[result.destination.parent] = None
        return tuple(seen)
