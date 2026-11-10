# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Workflow policies and lifecycle with a fake engine (A02, A04, A05, A06, A12, A14)."""

import errno
import threading
from pathlib import Path

import pikepdf
import pytest

from searchify_pdf.application import workflow
from searchify_pdf.application.workflow import BatchRunner, NonInteractiveDecisions
from searchify_pdf.domain.jobs import JobEvent, JobState, Outcome, Reason
from searchify_pdf.domain.paths import lock_path_for
from searchify_pdf.domain.settings import (
    ExistingOutputPolicy,
    ExistingTextPolicy,
    Settings,
    WorkerMode,
)
from searchify_pdf.domain.text_quality import UNKNOWN, TextQuality, Verdict
from searchify_pdf.engines.base import EngineRequest, OcrMode
from searchify_pdf.engines.pdf_inspect import has_marker
from searchify_pdf.storage.locks import FileLock
from tests import synthetic
from tests.fakes import CANCEL, NO, NO_ALL, YES, YES_ALL, FakeEngine, ScriptedDecisions
from tests.textutil import sha256

GIB = 1024**3


def runner(
    settings: Settings | None = None, engine: FakeEngine | None = None, **kw: object
) -> BatchRunner:
    return BatchRunner(
        settings or Settings(),
        engine or FakeEngine(),
        version="9.9.9",
        resources=lambda: (8, 64 * GIB),
        **kw,  # type: ignore[arg-type]
    )


def test_single_file_converted_with_marker(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "Acme.pdf", (["a"], ["b"]))
    before = sha256(src)
    events: list[JobEvent] = []
    summary = runner(on_event=events.append).run([src])
    result = summary.results[0]
    assert result.outcome is Outcome.CONVERTED
    assert result.destination == tmp_path / "Acme_searchable.pdf"
    assert has_marker(result.destination)
    assert result.pages.inspected == 2 and result.pages.ocr_processed == 2
    assert sha256(src) == before
    states = [e.state for e in events]
    assert states == [
        JobState.DISCOVERED,
        JobState.DECIDING,
        JobState.QUEUED,
        JobState.RUNNING,
        JobState.VALIDATING,
        JobState.PUBLISHING,
        JobState.FINISHED,
    ]
    assert events[-1].result == result
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Acme.pdf", "Acme_searchable.pdf"]
    assert summary.succeeded and summary.folders == (tmp_path,)


def test_folder_recursive_adjacent_and_repeat_run(tmp_path: Path) -> None:
    (tmp_path / "Contracts" / "2025").mkdir(parents=True)
    a = synthetic.scanned_pdf(tmp_path / "Contracts" / "2025" / "Acme.pdf")
    b = synthetic.scanned_pdf(tmp_path / "Contracts" / "Grüße Ä.pdf")
    first = runner().run([tmp_path])
    assert [r.outcome for r in first.results] == [Outcome.CONVERTED, Outcome.CONVERTED]
    assert (a.parent / "Acme_searchable.pdf").exists()
    assert (b.parent / "Grüße Ä_searchable.pdf").exists()
    again = runner(Settings(existing_output_policy=ExistingOutputPolicy.NEVER_OVERWRITE)).run(
        [tmp_path]
    )
    assert [r.outcome for r in again.results] == [Outcome.SKIPPED, Outcome.SKIPPED]
    assert {o.reason for o in again.omissions} == {Reason.GENERATED_COPY}
    assert not list(tmp_path.rglob("*_searchable_searchable.pdf"))
    assert not (tmp_path / "output").exists()


def test_suffix_change_still_excludes_old_copies(tmp_path: Path) -> None:
    synthetic.scanned_pdf(tmp_path / "a.pdf")
    runner().run([tmp_path])
    changed = Settings().with_changes(output_suffix="_ocr")
    summary = runner(changed).run([tmp_path])
    assert [r.outcome for r in summary.results] == [Outcome.CONVERTED]
    assert (tmp_path / "a_ocr.pdf").exists()
    assert not (tmp_path / "a_searchable_ocr.pdf").exists()


def test_ask_output_noninteractive_requires_action(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    dest = tmp_path / "a_searchable.pdf"
    dest.write_bytes(b"previous")
    summary = runner(decisions=NonInteractiveDecisions()).run([src])
    assert summary.results[0].outcome is Outcome.ACTION_REQUIRED
    assert summary.results[0].reason is Reason.ASK_NONINTERACTIVE
    assert dest.read_bytes() == b"previous"
    assert not summary.succeeded


def test_ask_output_choices_and_batch(tmp_path: Path) -> None:
    sources = [synthetic.scanned_pdf(tmp_path / f"{n}.pdf") for n in "abcd"]
    for s in sources:
        (tmp_path / f"{s.stem}_searchable.pdf").write_bytes(b"previous")
    decisions = ScriptedDecisions(output=[NO, YES_ALL])
    summary = runner(decisions=decisions).run(sources)
    assert [r.outcome for r in summary.results] == [
        Outcome.SKIPPED,
        Outcome.CONVERTED,
        Outcome.CONVERTED,
        Outcome.CONVERTED,
    ]
    assert len(decisions.asked) == 2  # batch choice reused, not saved as a preference
    assert (tmp_path / "a_searchable.pdf").read_bytes() == b"previous"
    assert has_marker(tmp_path / "d_searchable.pdf")


def test_ask_output_no_to_all_and_cancel(tmp_path: Path) -> None:
    sources = [synthetic.scanned_pdf(tmp_path / f"{n}.pdf") for n in "abc"]
    for s in sources:
        (tmp_path / f"{s.stem}_searchable.pdf").write_bytes(b"previous")
    summary = runner(decisions=ScriptedDecisions(output=[NO_ALL])).run(sources)
    assert [r.outcome for r in summary.results] == [Outcome.SKIPPED] * 3
    cancelled = runner(decisions=ScriptedDecisions(output=[CANCEL])).run(sources)
    assert [r.outcome for r in cancelled.results] == [Outcome.CANCELLED] * 3


def test_overwrite_failure_keeps_previous_output(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    dest = tmp_path / "a_searchable.pdf"
    dest.write_bytes(b"previous valid copy")
    s = Settings(existing_output_policy=ExistingOutputPolicy.OVERWRITE)
    summary = runner(s, FakeEngine(fail=Reason.ENGINE_FAILED)).run([src])
    result = summary.results[0]
    assert result.outcome is Outcome.FAILED and result.reason is Reason.ENGINE_FAILED
    assert result.destination is None and result.pages.failed == 1
    assert dest.read_bytes() == b"previous valid copy"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf", "a_searchable.pdf"]
    ok = runner(s).run([src])
    assert ok.results[0].outcome is Outcome.CONVERTED and has_marker(dest)


def test_existing_text_policies(tmp_path: Path) -> None:
    digital = synthetic.digital_pdf(tmp_path / "digital.pdf")
    mixed = synthetic.mixed_pdf(tmp_path / "mixed.pdf")
    engine = FakeEngine()
    never = runner(engine=engine).run([digital, mixed])
    by_name = {r.source.name: r for r in never.results}
    assert by_name["digital.pdf"].outcome is Outcome.PRESERVED
    assert by_name["digital.pdf"].pages.preserved == 1
    assert by_name["mixed.pdf"].outcome is Outcome.CONVERTED
    assert (
        by_name["mixed.pdf"].pages.ocr_processed == 1 and by_name["mixed.pdf"].pages.preserved == 1
    )
    assert [r.mode for r in engine.requests] == [OcrMode.PRESERVE_TEXT]
    assert has_marker(tmp_path / "digital_searchable.pdf")

    for p in tmp_path.glob("*_searchable.pdf"):
        p.unlink()
    engine = FakeEngine()
    always = runner(Settings(existing_text_policy=ExistingTextPolicy.ALWAYS_REPLACE), engine).run(
        [digital, mixed]
    )
    assert [r.outcome for r in always.results] == [Outcome.CONVERTED, Outcome.CONVERTED]
    assert {r.mode for r in engine.requests} == {OcrMode.REDO_OCR}
    assert always.results[0].pages.ocr_processed == 1


def test_existing_text_ask(tmp_path: Path) -> None:
    digital = synthetic.digital_pdf(tmp_path / "digital.pdf")
    mixed = synthetic.mixed_pdf(tmp_path / "mixed.pdf")
    scan = synthetic.scanned_pdf(tmp_path / "scan.pdf")
    ask = Settings(existing_text_policy=ExistingTextPolicy.ASK)
    none = runner(ask).run([digital])
    assert none.results[0].outcome is Outcome.ACTION_REQUIRED
    decisions = ScriptedDecisions(text=[YES, NO])
    engine = FakeEngine()
    summary = runner(ask, engine, decisions=decisions).run([digital, mixed, scan])
    assert [kind for kind, _ in decisions.asked] == ["text", "text"]  # scan has no text: not asked
    assert [r.outcome for r in summary.results] == [
        Outcome.CONVERTED,
        Outcome.CONVERTED,
        Outcome.CONVERTED,
    ]
    assert [r.mode for r in engine.requests] == [
        OcrMode.REDO_OCR,
        OcrMode.PRESERVE_TEXT,
        OcrMode.PRESERVE_TEXT,
    ]


def test_existing_text_ask_batch_and_cancel(tmp_path: Path) -> None:
    a = synthetic.digital_pdf(tmp_path / "a.pdf")
    b = synthetic.digital_pdf(tmp_path / "b.pdf")
    ask = Settings(existing_text_policy=ExistingTextPolicy.ASK)
    decisions = ScriptedDecisions(text=[NO_ALL])
    summary = runner(ask, decisions=decisions).run([a, b])
    assert [r.outcome for r in summary.results] == [Outcome.PRESERVED, Outcome.PRESERVED]
    assert len(decisions.asked) == 1
    for p in tmp_path.glob("*_searchable.pdf"):
        p.unlink()
    cancelled = runner(ask, decisions=ScriptedDecisions(text=[CANCEL])).run([a, b])
    assert [r.outcome for r in cancelled.results] == [Outcome.CANCELLED, Outcome.CANCELLED]


POOR = TextQuality(0.2, 1, Verdict.POOR)
DOUBTFUL = TextQuality(0.7, 1, Verdict.DOUBTFUL)
GOOD = TextQuality(0.98, 1, Verdict.GOOD)


def test_ask_shows_the_cross_check_and_notes_kept_poor_text(tmp_path: Path) -> None:
    """#6: the check runs before asking; keeping doubtful/poor text leaves a note."""
    digital = synthetic.digital_pdf(tmp_path / "digital.pdf")
    mixed = synthetic.mixed_pdf(tmp_path / "mixed.pdf")
    scan = synthetic.scanned_pdf(tmp_path / "scan.pdf")
    ask = Settings(existing_text_policy=ExistingTextPolicy.ASK)
    engine = FakeEngine(quality=POOR)
    decisions = ScriptedDecisions(text=[NO, YES])
    summary = runner(ask, engine, decisions=decisions).run([digital, mixed, scan])
    assert engine.checked == [digital, mixed]  # the scan has no text: nothing to check
    assert decisions.qualities == [POOR, POOR]
    kept, replaced, scanned = summary.results
    assert kept.outcome is Outcome.PRESERVED and kept.notes == (Reason.EXISTING_TEXT_POOR,)
    assert replaced.outcome is Outcome.CONVERTED and replaced.notes == ()
    assert scanned.notes == ()


@pytest.mark.parametrize(
    ("quality", "notes"),
    [(DOUBTFUL, (Reason.EXISTING_TEXT_DOUBTFUL,)), (GOOD, ()), (UNKNOWN, ())],
)
def test_kept_text_notes_follow_the_verdict(
    tmp_path: Path, quality: TextQuality, notes: tuple[Reason, ...]
) -> None:
    src = synthetic.mixed_pdf(tmp_path / "mixed.pdf")
    ask = Settings(existing_text_policy=ExistingTextPolicy.ASK)
    summary = runner(ask, FakeEngine(quality=quality), decisions=ScriptedDecisions(text=[NO])).run(
        [src]
    )
    assert summary.results[0].outcome is Outcome.CONVERTED
    assert summary.results[0].notes == notes


def test_noninteractive_ask_still_runs_no_prompt(tmp_path: Path) -> None:
    src = synthetic.digital_pdf(tmp_path / "a.pdf")
    ask = Settings(existing_text_policy=ExistingTextPolicy.ASK)
    engine = FakeEngine(quality=POOR)
    summary = runner(ask, engine).run([src])
    assert summary.results[0].outcome is Outcome.ACTION_REQUIRED
    assert engine.checked == [src]


def test_cross_check_skipped_when_disabled_policy_fixed_or_replacing_anyway(
    tmp_path: Path,
) -> None:
    a = synthetic.digital_pdf(tmp_path / "a.pdf")
    b = synthetic.digital_pdf(tmp_path / "b.pdf")
    off = Settings(existing_text_policy=ExistingTextPolicy.ASK, cross_check_existing_text=False)
    engine = FakeEngine(quality=POOR)
    decisions = ScriptedDecisions(text=[NO, NO])
    summary = runner(off, engine, decisions=decisions).run([a, b])
    assert engine.checked == [] and decisions.qualities == [None, None]
    assert all(r.notes == () for r in summary.results)
    for policy in (ExistingTextPolicy.NEVER_REPLACE, ExistingTextPolicy.ALWAYS_REPLACE):
        for p in tmp_path.glob("*_searchable.pdf"):
            p.unlink()
        runner(Settings(existing_text_policy=policy), engine).run([a])
        assert engine.checked == []
    for p in tmp_path.glob("*_searchable.pdf"):
        p.unlink()
    ask = Settings(existing_text_policy=ExistingTextPolicy.ASK)
    runner(ask, engine, decisions=ScriptedDecisions(text=[YES_ALL])).run([a, b])
    assert engine.checked == [a]  # "replace all": the second document is not checked


def test_keep_for_the_batch_still_notes_poor_text(tmp_path: Path) -> None:
    a = synthetic.digital_pdf(tmp_path / "a.pdf")
    b = synthetic.digital_pdf(tmp_path / "b.pdf")
    ask = Settings(existing_text_policy=ExistingTextPolicy.ASK)
    engine = FakeEngine(quality=POOR)
    decisions = ScriptedDecisions(text=[NO_ALL])
    summary = runner(ask, engine, decisions=decisions).run([a, b])
    assert len(decisions.asked) == 1 and engine.checked == [a, b]
    assert [r.notes for r in summary.results] == [(Reason.EXISTING_TEXT_POOR,)] * 2


def test_looks_generated_note_comes_first(tmp_path: Path) -> None:
    src = synthetic.mixed_pdf(tmp_path / "scan_searchable.pdf")  # selected explicitly
    ask = Settings(existing_text_policy=ExistingTextPolicy.ASK)
    summary = runner(ask, FakeEngine(quality=POOR), decisions=ScriptedDecisions(text=[NO])).run(
        [src]
    )
    assert summary.results[0].notes == (Reason.LOOKS_GENERATED, Reason.EXISTING_TEXT_POOR)


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (synthetic.encrypted_pdf, Reason.PASSWORD_REQUIRED),
        (lambda p: synthetic.encrypted_pdf(p, user_password=""), Reason.RESTRICTED),
        (synthetic.signed_pdf, Reason.SIGNED),
        (synthetic.corrupt_pdf, Reason.INVALID_PDF),
    ],
)
def test_protected_and_corrupt_inputs_rejected(
    tmp_path: Path, make: object, reason: Reason
) -> None:
    src = make(tmp_path / "x.pdf")  # type: ignore[operator]
    before = sha256(src)
    result = runner().run([src]).results[0]
    assert result.outcome is Outcome.FAILED and result.reason is reason
    assert sha256(src) == before
    assert not (tmp_path / "x_searchable.pdf").exists()


def test_marker_on_naturally_named_explicit_file(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "Report_searchable.pdf")
    result = runner().run([src]).results[0]
    assert result.outcome is Outcome.CONVERTED
    assert Reason.LOOKS_GENERATED in result.notes
    # a marked file with an ordinary name is recognised as our output during decision
    marked = synthetic.scanned_pdf(tmp_path / "renamed.pdf")
    with pikepdf.open(marked, allow_overwriting_input=True) as pdf:
        pdf.docinfo["/SearchifyPDF"] = "1"
        pdf.save(marked)
    again = runner().run([marked]).results[0]
    assert again.outcome is Outcome.SKIPPED and again.reason is Reason.GENERATED_COPY


def test_engine_not_ready(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    summary = runner(engine=FakeEngine(ready=(Reason.ENGINE_MISSING, "deu"))).run([src])
    assert summary.results[0].reason is Reason.ENGINE_MISSING
    assert summary.results[0].detail == "deu"
    empty = runner(engine=FakeEngine(ready=(Reason.ENGINE_MISSING, "x"))).run([tmp_path / "none"])
    assert empty.results == () and empty.omissions[0].reason is Reason.NOT_FOUND


def test_destination_symlink_rejected(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    (tmp_path / "a_searchable.pdf").symlink_to(tmp_path / "target.pdf")
    result = (
        runner(Settings(existing_output_policy=ExistingOutputPolicy.OVERWRITE))
        .run([src])
        .results[0]
    )
    assert result.reason is Reason.DESTINATION_SYMLINK
    assert not (tmp_path / "target.pdf").exists()


def test_locked_target_is_skipped(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    other = FileLock(lock_path_for(tmp_path / "a_searchable.pdf"))
    assert other.acquire()
    result = runner().run([src]).results[0]
    assert result.outcome is Outcome.SKIPPED and result.reason is Reason.LOCKED
    other.release()


def test_lock_creation_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")

    def boom(self: FileLock) -> bool:
        raise OSError(errno.EROFS, "read-only")

    monkeypatch.setattr(FileLock, "acquire", boom)
    result = runner().run([src]).results[0]
    assert result.outcome is Outcome.FAILED and result.reason is Reason.PERMISSION_DENIED


def test_output_created_by_someone_else_meanwhile(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    dest = tmp_path / "a_searchable.pdf"

    def writer(request: EngineRequest) -> None:
        request.output.write_bytes(src.read_bytes())
        dest.write_bytes(b"foreign")

    result = runner(engine=FakeEngine(writer=writer)).run([src]).results[0]
    assert result.outcome is Outcome.SKIPPED and result.reason is Reason.OUTPUT_EXISTS
    assert dest.read_bytes() == b"foreign"


def test_invalid_engine_output_not_published(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf", (["a"], ["b"]))

    def one_page(request: EngineRequest) -> None:
        synthetic.scanned_pdf(request.output, (["only"],))

    result = runner(engine=FakeEngine(writer=one_page)).run([src]).results[0]
    assert result.outcome is Outcome.FAILED and result.reason is Reason.VALIDATION_FAILED
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf"]

    def garbage(request: EngineRequest) -> None:
        request.output.write_bytes(b"garbage")

    result = runner(engine=FakeEngine(writer=garbage)).run([src]).results[0]
    assert result.reason is Reason.VALIDATION_FAILED


def test_disk_full_during_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")

    def full(*_: object, **__: object) -> None:
        raise OSError(errno.ENOSPC, "full")

    monkeypatch.setattr(workflow.shutil, "copyfile", full)
    digital = synthetic.digital_pdf(tmp_path / "d.pdf")
    result = runner().run([digital]).results[0]
    assert result.outcome is Outcome.FAILED and result.reason is Reason.DISK_FULL
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf", "d.pdf"]
    del src


def test_cancel_during_run_discards_partial_output(tmp_path: Path) -> None:
    sources = [synthetic.scanned_pdf(tmp_path / f"{i}.pdf") for i in range(6)]
    cancel = threading.Event()
    engine = FakeEngine(delay=5)

    def on_event(event: JobEvent) -> None:
        if event.state is JobState.RUNNING:
            cancel.set()

    s = Settings(worker_mode=WorkerMode.FIXED, fixed_workers=2)
    summary = runner(s, engine, cancel=cancel, on_event=on_event).run(sources)
    assert {r.outcome for r in summary.results} == {Outcome.CANCELLED}
    assert len(summary.results) == 6
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(s.name for s in sources)


def test_cancel_before_start(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    cancel = threading.Event()
    cancel.set()
    assert runner(cancel=cancel).run([src]).results[0].outcome is Outcome.CANCELLED


def test_cancel_after_engine_success(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    cancel = threading.Event()

    def writer(request: EngineRequest) -> None:
        request.output.write_bytes(src.read_bytes())
        cancel.set()

    result = runner(engine=FakeEngine(writer=writer), cancel=cancel).run([src]).results[0]
    assert result.outcome is Outcome.CANCELLED
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf"]


def test_cancel_while_queue_full(tmp_path: Path) -> None:
    sources = [synthetic.scanned_pdf(tmp_path / f"{i}.pdf") for i in range(5)]
    cancel = threading.Event()
    seen = []

    def on_event(event: JobEvent) -> None:
        if event.state is JobState.QUEUED:
            seen.append(event.job_id)
            if len(seen) == 2:
                threading.Timer(0.3, cancel.set).start()

    s = Settings(worker_mode=WorkerMode.SEQUENTIAL)
    summary = runner(s, FakeEngine(delay=3), cancel=cancel, on_event=on_event).run(sources)
    assert [r.outcome for r in summary.results] == [Outcome.CANCELLED] * 5


def test_worker_limit_is_respected_and_timed(tmp_path: Path) -> None:
    sources = [synthetic.scanned_pdf(tmp_path / f"{i}.pdf") for i in range(7)]
    engine = FakeEngine(delay=0.15)
    s = Settings(worker_mode=WorkerMode.FIXED, fixed_workers=3)
    r = runner(s, engine)
    summary = r.run(sources)
    assert engine.max_active <= 3
    assert engine.max_active >= 2
    assert summary.workers == 3 and r.plan is not None and r.plan.page_jobs == 2
    assert all(req.page_jobs == 2 for req in engine.requests)
    assert all(res.duration_seconds >= 0.1 for res in summary.results)
    assert summary.wall_seconds < sum(res.duration_seconds for res in summary.results)
    assert summary.count(Outcome.CONVERTED) == 7


def test_engine_reports_cancel(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    result = runner(engine=FakeEngine(fail=Reason.CANCELLED)).run([src]).results[0]
    assert result.outcome is Outcome.CANCELLED


def test_wait_for_slot_is_cancellable() -> None:
    r = runner()
    slots = threading.BoundedSemaphore(1)
    assert r._wait_for_slot(slots)
    timer = threading.Timer(0.2, r.cancel.set)
    timer.start()
    assert not r._wait_for_slot(slots)  # full queue, then cancelled
    timer.join()


def test_cancel_while_waiting_for_queue_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = [synthetic.scanned_pdf(tmp_path / f"{i}.pdf") for i in range(2)]
    r = runner()
    monkeypatch.setattr(r, "_wait_for_slot", lambda slots: False)  # cancelled while queue full
    summary = r.run(sources)
    assert [res.outcome for res in summary.results] == [Outcome.CANCELLED, Outcome.CANCELLED]
