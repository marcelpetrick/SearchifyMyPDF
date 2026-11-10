# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Batch workflow: snapshot → discover → decide → queue → run → validate → publish.

The workflow is UI-agnostic. It is driven from a background thread by the GUI and
directly by the CLI. Policy decisions (and therefore prompts) happen one at a time in
the driving thread, while up to ``documents`` conversions run in worker threads, each
delegating OCR to an isolated engine process.

Protected PDFs (ADR 0011): a password is asked for (or taken from the passwords the
batch already knows), the source is decrypted into a private temporary folder for the
engine, and the validated copy is encrypted again like the source before publishing.
"""

from __future__ import annotations

import dataclasses
import enum
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Protocol

from searchify_pdf.application.discovery import Candidate, discover
from searchify_pdf.application.scheduler import WorkerPlan, plan_workers, system_resources
from searchify_pdf.domain.jobs import (
    BatchSummary,
    JobEvent,
    JobResult,
    JobState,
    Omission,
    Outcome,
    PageCounts,
    Reason,
)
from searchify_pdf.domain.paths import lock_path_for
from searchify_pdf.domain.settings import ExistingOutputPolicy, ExistingTextPolicy, Settings
from searchify_pdf.engines.base import EngineRequest, OcrEngine, OcrMode
from searchify_pdf.engines.pdf_inspect import (
    PdfInfo,
    PdfInspectionError,
    add_marker,
    decrypt_copy,
    encrypt_like,
    has_marker,
    inspect_pdf,
)
from searchify_pdf.storage.locks import FileLock
from searchify_pdf.storage.publisher import (
    PublishError,
    destination_problem,
    discard,
    new_staging_path,
    publish,
    reason_for_os_error,
    remove_stale_staging,
    validate_output,
)


class Choice(enum.StrEnum):
    YES = "yes"  # overwrite the copy / replace the existing OCR
    NO = "no"  # skip / keep existing text
    CANCEL = "cancel"  # stop the whole batch


@dataclasses.dataclass(frozen=True, slots=True)
class Decision:
    choice: Choice
    apply_to_batch: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class PasswordAnswer:
    """YES with ``password`` to try it, NO to skip the document, CANCEL to stop the batch."""

    choice: Choice
    password: str = dataclasses.field(default="", repr=False)


MAX_PASSWORD_ATTEMPTS = 3


class DecisionProvider(Protocol):
    """Answers "Ask me" policies. ``None`` means no interactive answer is possible."""

    def existing_output(self, source: Path, destination: Path) -> Decision | None: ...

    def existing_text(self, source: Path, text_pages: int, total_pages: int) -> Decision | None: ...

    def password(self, source: Path, retry: bool) -> PasswordAnswer | None:
        """Ask for the password of ``source``; ``retry`` after a wrong one."""
        ...


class NonInteractiveDecisions:
    """CLI without a terminal: never hang, never silently authorize replacement."""

    def existing_output(self, source: Path, destination: Path) -> Decision | None:
        return None

    def existing_text(self, source: Path, text_pages: int, total_pages: int) -> Decision | None:
        return None

    def password(self, source: Path, retry: bool) -> PasswordAnswer | None:
        return None


@dataclasses.dataclass(frozen=True, slots=True)
class _Plan:
    job_id: int
    candidate: Candidate
    info: PdfInfo
    overwrite: bool
    mode: OcrMode | None  # None → every page already has text: publish an unchanged copy
    notes: tuple[Reason, ...]
    submitted: float


EventSink = Callable[[JobEvent], None]
NO_PAGES = PageCounts()


class BatchRunner:
    def __init__(
        self,
        settings: Settings,
        engine: OcrEngine,
        *,
        decisions: DecisionProvider | None = None,
        on_event: EventSink | None = None,
        cancel: threading.Event | None = None,
        version: str = "0",
        clock: Callable[[], float] = time.monotonic,
        resources: Callable[[], tuple[int, int]] = system_resources,
        passwords: Sequence[str] = (),
    ) -> None:
        self.settings = settings  # immutable snapshot for this batch
        self.engine = engine
        self.decisions = decisions or NonInteractiveDecisions()
        self.on_event = on_event or (lambda _event: None)
        self.cancel = cancel or threading.Event()
        self.version = version
        self.clock = clock
        self.resources = resources
        self.plan: WorkerPlan | None = None
        self._batch_output: Choice | None = None
        self._batch_text: Choice | None = None
        # Passwords given up front or entered during this batch, tried before asking
        # again (a folder of statements usually shares one). Memory only, never stored.
        self._passwords: list[str] = [p for p in dict.fromkeys(passwords) if p]

    # -- public -------------------------------------------------------------------------

    def run(self, inputs: Sequence[Path]) -> BatchSummary:
        started = self.clock()
        s = self.settings
        found = discover(inputs, s.output_suffix, s.known_suffixes, has_marker)
        results: list[JobResult] = []
        cpu, memory = self.resources()
        self.plan = plan_workers(s, len(found.candidates), cpu_count=cpu, available_memory=memory)
        for job_id, candidate in enumerate(found.candidates):
            self._emit(job_id, candidate.source, JobState.DISCOVERED)

        problem = self.engine.readiness_problem(s.ocr_languages) if found.candidates else None
        if problem is not None:
            reason, detail = problem
            for job_id, candidate in enumerate(found.candidates):
                results.append(self._finish(job_id, candidate, Outcome.FAILED, reason, detail))
            return self._summary(results, found.omissions, started)

        slots = threading.BoundedSemaphore(self.plan.documents * 2)  # bounded queue
        futures: list[Future[JobResult]] = []
        with ThreadPoolExecutor(self.plan.documents, thread_name_prefix="searchify") as pool:
            for job_id, candidate in enumerate(found.candidates):
                if self.cancel.is_set():
                    results.append(
                        self._finish(job_id, candidate, Outcome.CANCELLED, Reason.CANCELLED)
                    )
                    continue
                planned = self._decide(job_id, candidate)
                if isinstance(planned, JobResult):
                    results.append(planned)
                    continue
                if not self._wait_for_slot(slots):
                    results.append(
                        self._finish(job_id, candidate, Outcome.CANCELLED, Reason.CANCELLED)
                    )
                    continue
                self._emit(job_id, candidate.source, JobState.QUEUED)
                future = pool.submit(self._execute, planned)
                future.add_done_callback(lambda _f: slots.release())
                futures.append(future)
            results.extend(future.result() for future in futures)
        results.sort(key=lambda r: r.job_id)
        return self._summary(results, found.omissions, started)

    def _wait_for_slot(self, slots: threading.BoundedSemaphore) -> bool:
        """Block until the bounded queue has room; False when the batch was cancelled."""
        while not self.cancel.is_set():
            if slots.acquire(timeout=0.1):
                return True
        return False

    # -- decisions ---------------------------------------------------------------------

    def _decide(self, job_id: int, candidate: Candidate) -> _Plan | JobResult:
        self._emit(job_id, candidate.source, JobState.DECIDING)
        problem = destination_problem(candidate.source, candidate.destination)
        if problem is not None:
            return self._finish(job_id, candidate, Outcome.FAILED, problem)
        info = self._inspect(job_id, candidate)
        if isinstance(info, JobResult):
            return info
        pages = PageCounts(inspected=info.page_count)
        if info.signed:
            return self._finish(job_id, candidate, Outcome.FAILED, Reason.SIGNED, pages=pages)
        protection = info.protection
        if (
            protection is not None
            and protection.restricted_only
            and not self.settings.process_restricted_pdfs
        ):
            return self._finish(job_id, candidate, Outcome.FAILED, Reason.RESTRICTED, pages=pages)
        if info.generated_marker:
            return self._finish(job_id, candidate, Outcome.SKIPPED, Reason.GENERATED_COPY)

        overwrite = False
        if candidate.destination.exists():
            choice = self._output_choice(candidate)
            if choice is None:
                return self._finish(
                    job_id, candidate, Outcome.ACTION_REQUIRED, Reason.ASK_NONINTERACTIVE
                )
            if choice is Choice.CANCEL:
                self.cancel.set()
                return self._finish(job_id, candidate, Outcome.CANCELLED, Reason.CANCELLED)
            if choice is Choice.NO:
                return self._finish(job_id, candidate, Outcome.SKIPPED, Reason.OUTPUT_EXISTS)
            overwrite = True

        mode: OcrMode | None = OcrMode.PRESERVE_TEXT
        if info.any_text:
            choice = self._text_choice(candidate, info)
            if choice is None:
                return self._finish(
                    job_id, candidate, Outcome.ACTION_REQUIRED, Reason.ASK_NONINTERACTIVE
                )
            if choice is Choice.CANCEL:
                self.cancel.set()
                return self._finish(job_id, candidate, Outcome.CANCELLED, Reason.CANCELLED)
            if choice is Choice.YES:
                mode = OcrMode.REDO_OCR
            elif info.all_text:
                mode = None
        notes = (Reason.LOOKS_GENERATED,) if candidate.looks_generated else ()
        return _Plan(job_id, candidate, info, overwrite, mode, notes, self.clock())

    def _inspect(self, job_id: int, candidate: Candidate) -> PdfInfo | JobResult:
        """Inspect the source, unlocking it with a known or asked-for password if needed."""

        def failed(error: PdfInspectionError) -> JobResult:
            return self._finish(job_id, candidate, Outcome.FAILED, error.reason, error.detail)

        def attempt(password: str = "") -> PdfInfo | PdfInspectionError:
            try:
                return inspect_pdf(candidate.source, password)
            except PdfInspectionError as error:
                return error

        locked = {Reason.PASSWORD_REQUIRED, Reason.WRONG_PASSWORD}
        result = attempt()
        if isinstance(result, PdfInfo):
            return result
        if result.reason is not Reason.PASSWORD_REQUIRED:
            return failed(result)
        for password in self._passwords:
            result = attempt(password)
            if isinstance(result, PdfInfo):
                return result
            if result.reason not in locked:
                return failed(result)
        retry = False
        for _attempt in range(MAX_PASSWORD_ATTEMPTS):
            answer = self.decisions.password(candidate.source, retry)
            if answer is None:
                return self._finish(job_id, candidate, Outcome.FAILED, Reason.PASSWORD_REQUIRED)
            if answer.choice is Choice.CANCEL:
                self.cancel.set()
                return self._finish(job_id, candidate, Outcome.CANCELLED, Reason.CANCELLED)
            if answer.choice is Choice.NO:
                return self._finish(job_id, candidate, Outcome.SKIPPED, Reason.USER_SKIPPED)
            result = attempt(answer.password)
            if isinstance(result, PdfInfo):
                self._passwords.append(answer.password)
                return result
            if result.reason not in locked:
                return failed(result)
            retry = True
        return self._finish(job_id, candidate, Outcome.FAILED, Reason.WRONG_PASSWORD)

    def _output_choice(self, candidate: Candidate) -> Choice | None:
        policy = self.settings.existing_output_policy
        if policy is ExistingOutputPolicy.OVERWRITE:
            return Choice.YES
        if policy is ExistingOutputPolicy.NEVER_OVERWRITE:
            return Choice.NO
        if self._batch_output is not None:
            return self._batch_output
        decision = self.decisions.existing_output(candidate.source, candidate.destination)
        if decision is None:
            return None
        if decision.apply_to_batch and decision.choice is not Choice.CANCEL:
            self._batch_output = decision.choice
        return decision.choice

    def _text_choice(self, candidate: Candidate, info: PdfInfo) -> Choice | None:
        policy = self.settings.existing_text_policy
        if policy is ExistingTextPolicy.ALWAYS_REPLACE:
            return Choice.YES
        if policy is ExistingTextPolicy.NEVER_REPLACE:
            return Choice.NO
        if self._batch_text is not None:
            return self._batch_text
        decision = self.decisions.existing_text(
            candidate.source, info.text_page_count, info.page_count
        )
        if decision is None:
            return None
        if decision.apply_to_batch and decision.choice is not Choice.CANCEL:
            self._batch_text = decision.choice
        return decision.choice

    # -- execution ---------------------------------------------------------------------

    def _execute(self, plan: _Plan) -> JobResult:
        candidate, info = plan.candidate, plan.info
        start = self.clock()
        queue_seconds = start - plan.submitted
        pages = self._page_counts(plan)

        def done(
            outcome: Outcome,
            reason: Reason,
            detail: str = "",
            *,
            pages: PageCounts = NO_PAGES,
            notes: tuple[Reason, ...] = (),
        ) -> JobResult:
            return self._finish(
                plan.job_id,
                candidate,
                outcome,
                reason,
                detail,
                duration=self.clock() - start,
                queue=queue_seconds,
                pages=pages,
                notes=plan.notes + notes,
            )

        if self.cancel.is_set():
            return done(Outcome.CANCELLED, Reason.CANCELLED)
        self._emit(plan.job_id, candidate.source, JobState.RUNNING)
        lock = FileLock(lock_path_for(candidate.destination))
        try:
            acquired = lock.acquire()
        except OSError as exc:
            return done(Outcome.FAILED, reason_for_os_error(exc), str(exc))
        if not acquired:
            return done(Outcome.SKIPPED, Reason.LOCKED)
        remove_stale_staging(candidate.destination)
        staging = new_staging_path(candidate.destination)
        engine_notes: tuple[Reason, ...] = ()
        protection = info.protection
        # Decrypted content never goes beside the original: protected documents are
        # unlocked into a private (0700) temporary folder that is always removed.
        workdir = Path(tempfile.mkdtemp(prefix="searchify-")) if protection else None
        try:
            engine_source, engine_output = candidate.source, staging
            if protection is not None and workdir is not None:
                engine_source, engine_output = workdir / "source.pdf", workdir / "copy.pdf"
                decrypt_copy(candidate.source, protection.password, engine_source)
            if plan.mode is None:
                shutil.copyfile(engine_source, engine_output)
            else:
                request = EngineRequest(
                    engine_source,
                    engine_output,
                    self.settings.ocr_languages,
                    plan.mode,
                    deskew=self.settings.deskew,
                    rotate_pages=self.settings.rotate_pages,
                    page_jobs=self.plan.page_jobs if self.plan else 1,
                    timeout_seconds=float(self.settings.timeout_seconds),
                )
                result = self.engine.run(request, self.cancel)
                engine_notes = result.notes
                if not result.ok:
                    outcome = (
                        Outcome.CANCELLED if result.reason is Reason.CANCELLED else Outcome.FAILED
                    )
                    failed = dataclasses.replace(pages, failed=info.page_count, ocr_processed=0)
                    return done(
                        outcome, result.reason, result.detail, pages=failed, notes=engine_notes
                    )
            if self.cancel.is_set():
                return done(Outcome.CANCELLED, Reason.CANCELLED, notes=engine_notes)
            self._emit(plan.job_id, candidate.source, JobState.VALIDATING)
            add_marker(engine_output, self.version)
            if protection is not None:
                validate_output(engine_output, info.page_count)
                encrypt_like(engine_output, staging, protection)
            validate_output(staging, info.page_count, protection.password if protection else "")
            self._emit(plan.job_id, candidate.source, JobState.PUBLISHING)
            publish(staging, candidate.destination, overwrite=plan.overwrite)
        except PublishError as exc:
            outcome = Outcome.SKIPPED if exc.reason is Reason.OUTPUT_EXISTS else Outcome.FAILED
            return done(outcome, exc.reason, exc.detail, notes=engine_notes)
        except OSError as exc:
            return done(Outcome.FAILED, reason_for_os_error(exc), str(exc), notes=engine_notes)
        except Exception as exc:  # e.g. pikepdf failing on a damaged engine output
            return done(Outcome.FAILED, Reason.VALIDATION_FAILED, str(exc), notes=engine_notes)
        finally:
            discard(staging)
            if workdir is not None:
                shutil.rmtree(workdir, ignore_errors=True)
            lock.release()
        if plan.mode is None:
            return done(Outcome.PRESERVED, Reason.ALL_PAGES_HAVE_TEXT, pages=pages)
        return done(Outcome.CONVERTED, Reason.OK, pages=pages, notes=engine_notes)

    @staticmethod
    def _page_counts(plan: _Plan) -> PageCounts:
        info = plan.info
        if plan.mode is None:
            return PageCounts(inspected=info.page_count, preserved=info.page_count)
        if plan.mode is OcrMode.REDO_OCR:
            return PageCounts(inspected=info.page_count, ocr_processed=info.page_count)
        return PageCounts(
            inspected=info.page_count,
            ocr_processed=info.page_count - info.text_page_count,
            preserved=info.text_page_count,
        )

    # -- helpers -----------------------------------------------------------------------

    def _emit(
        self, job_id: int, source: Path, state: JobState, result: JobResult | None = None
    ) -> None:
        self.on_event(JobEvent(job_id, source, state, result))

    def _finish(
        self,
        job_id: int,
        candidate: Candidate,
        outcome: Outcome,
        reason: Reason,
        detail: str = "",
        *,
        duration: float = 0.0,
        queue: float = 0.0,
        pages: PageCounts = NO_PAGES,
        notes: tuple[Reason, ...] = (),
    ) -> JobResult:
        written = outcome in {Outcome.CONVERTED, Outcome.PRESERVED}
        result = JobResult(
            job_id,
            candidate.source,
            candidate.destination if written else None,
            outcome,
            reason,
            detail,
            duration,
            queue,
            pages,
            notes,
        )
        self._emit(job_id, candidate.source, JobState.FINISHED, result)
        return result

    def _summary(
        self, results: list[JobResult], omissions: tuple[Omission, ...], started: float
    ) -> BatchSummary:
        return BatchSummary(
            tuple(results),
            omissions,
            self.clock() - started,
            self.plan.documents if self.plan else 1,
        )
