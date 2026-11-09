# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Offscreen UI tests (A07, A09, A11): drop/run/cancel, prompts, save/close, themes, i18n."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent, QFileOpenEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from searchify_pdf.application.workflow import Choice, Decision
from searchify_pdf.domain.jobs import Outcome
from searchify_pdf.domain.settings import (
    ExistingOutputPolicy,
    Settings,
    Theme,
    UiLanguage,
    WorkerMode,
)
from searchify_pdf.storage.settings_repository import SETTINGS_FILE_NAME, SettingsRepository
from searchify_pdf.ui import app as app_module
from searchify_pdf.ui import theme
from searchify_pdf.ui.batch_thread import BatchThread, GuiDecisions, _PromptBridge
from searchify_pdf.ui.main_window import FileOpenFilter, MainWindow
from tests import synthetic
from tests.fakes import FakeEngine

pytestmark = pytest.mark.ui
Std = QMessageBox.StandardButton


class Messages:
    """Scripted replacement for modal message boxes."""

    def __init__(self, *answers: QMessageBox.StandardButton) -> None:
        self.answers = list(answers)
        self.shown: list[str] = []

    def __call__(
        self, icon: Any, title: str, text: str, buttons: Any
    ) -> QMessageBox.StandardButton:
        self.shown.append(text)
        return self.answers.pop(0) if self.answers else Std.Ok


def make_window(
    qtbot: QtBot, home: Path, engine: FakeEngine | None = None, **kw: Any
) -> MainWindow:
    fake = engine or FakeEngine()
    window = MainWindow(SettingsRepository(home), lambda: fake, **kw)
    window.message = Messages()
    qtbot.addWidget(window)
    return window


def run_and_wait(qtbot: QtBot, window: MainWindow, timeout: int = 20000) -> None:
    window.start()
    qtbot.waitUntil(lambda: not window.running, timeout=timeout)


def test_opens_with_defaults_and_english(qtbot: QtBot, tmp_path: Path) -> None:
    window = make_window(qtbot, tmp_path)
    assert window.tabs.count() == 4
    assert window.tabs.tabText(0) == "Convert"
    assert not window.start_button.isEnabled() and not window.cancel_button.isEnabled()
    assert window.language_boxes["eng"].isChecked() and window.language_boxes["deu"].isChecked()
    assert window.output_policy_combo.currentData() == ExistingOutputPolicy.ASK.value
    assert not window.stats_box.isChecked()
    assert not window.dirty
    assert "Fake" in window.engine_label.text()
    assert window.components_table.rowCount() > 3
    assert "disabled" in window.stats_view.toPlainText() or "off" in window.stats_view.toPlainText()


def test_add_paths_dedup_and_clear(qtbot: QtBot, tmp_path: Path) -> None:
    window = make_window(qtbot, tmp_path)
    a = synthetic.scanned_pdf(tmp_path / "a.pdf")
    window.add_paths([a, a, tmp_path / "." / "a.pdf"])
    assert window.queue == [a] and window.table.rowCount() == 1
    assert window.start_button.isEnabled()
    window.file_picker = lambda: [str(a), ""]
    window.choose_files()
    window.folder_picker = lambda: ""
    window.choose_folder()
    window.folder_picker = lambda: str(tmp_path)
    window.choose_folder()
    assert window.queue == [a, tmp_path]
    window.clear_queue()
    assert window.queue == [] and window.table.rowCount() == 0


_KEEP_ALIVE: list[QMimeData] = []  # events only reference the mime data


def _drop(widget: Any, paths: list[Path]) -> tuple[QDragEnterEvent, QDropEvent]:
    mime = QMimeData()
    _KEEP_ALIVE.append(mime)
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    enter = QDragEnterEvent(
        QPointF(widget.rect().center()),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    drop = QDropEvent(
        QPointF(widget.rect().center()),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    return enter, drop


def test_drag_and_drop_into_window(qtbot: QtBot, tmp_path: Path) -> None:
    window = make_window(qtbot, tmp_path)
    a = synthetic.scanned_pdf(tmp_path / "a.pdf")
    enter, drop = _drop(window, [a])
    window.dragEnterEvent(enter)
    assert enter.isAccepted()
    window.dropEvent(drop)
    window.drop_zone.dragLeaveEvent(enter)
    assert window.queue == [a]
    _, empty_drop = _drop(window, [])
    plain = QMimeData()
    _KEEP_ALIVE.append(plain)
    plain.setText("x")
    text_enter = QDragEnterEvent(
        QPointF(window.rect().center()),
        Qt.DropAction.CopyAction,
        plain,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.drop_zone.dragEnterEvent(text_enter)
    assert not text_enter.isAccepted()
    window.drop_zone.dropEvent(empty_drop)
    assert window.queue == [a]


def test_run_converts_and_reports(qtbot: QtBot, tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    synthetic.scanned_pdf(docs / "sub" / "a.pdf")
    synthetic.digital_pdf(docs / "b.pdf")
    synthetic.corrupt_pdf(docs / "c.pdf")
    (docs / "x_searchable.pdf").write_bytes(b"%PDF")
    opened: list[Path] = []
    window = make_window(qtbot, tmp_path)
    window.folder_opener = opened.append
    window.add_paths([docs])
    run_and_wait(qtbot, window)
    assert window.last_summary is not None
    assert window.last_summary.count(Outcome.CONVERTED) == 1
    assert window.last_summary.count(Outcome.PRESERVED) == 1
    assert window.last_summary.count(Outcome.FAILED) == 1
    statuses = [window.table.item(r, 2).text() for r in range(window.table.rowCount())]
    assert any("Converted" in s for s in statuses) and any("Failed" in s for s in statuses)
    assert "1 converted" in window.summary_label.text()
    assert "not processed" in window.summary_label.text()
    assert window.open_button.isEnabled()
    window.open_result_folder()
    assert opened and opened[0] in {docs, docs / "sub"}
    assert window.progress.value() == 1
    assert window.status_label.text() == "Ready."


def test_ask_prompt_and_cancel(qtbot: QtBot, tmp_path: Path) -> None:
    a = synthetic.scanned_pdf(tmp_path / "a.pdf")
    (tmp_path / "a_searchable.pdf").write_bytes(b"old")
    window = make_window(qtbot, tmp_path)
    asked: list[str] = []

    def prompter(kind: str, payload: dict[str, object]) -> Decision:
        asked.append(kind)
        return Decision(Choice.YES)

    window.prompter = prompter
    window.add_paths([a])
    run_and_wait(qtbot, window)
    assert asked == ["output"]
    assert (tmp_path / "a_searchable.pdf").read_bytes() != b"old"


def test_cancel_running_batch(qtbot: QtBot, tmp_path: Path) -> None:
    sources = [synthetic.scanned_pdf(tmp_path / f"{i}.pdf") for i in range(3)]
    window = make_window(qtbot, tmp_path, FakeEngine(delay=10))
    window.add_paths(sources)
    window.start()
    assert window.running and window.cancel_button.isEnabled()
    window.start()  # second start while running is ignored
    qtbot.waitUntil(lambda: window.finished_count > 0 or window.total > 0, timeout=5000)
    window.cancel()
    assert window.status_label.text() == "Cancelling…"
    qtbot.waitUntil(lambda: not window.running, timeout=20000)
    assert window.last_summary is not None
    assert window.last_summary.count(Outcome.CANCELLED) == 3
    assert sorted(p.name for p in tmp_path.glob("*.pdf")) == ["0.pdf", "1.pdf", "2.pdf"]


def test_settings_save_and_language_switch(qtbot: QtBot, tmp_path: Path) -> None:
    window = make_window(qtbot, tmp_path)
    window.ui_language_combo.setCurrentIndex(
        window.ui_language_combo.findData(UiLanguage.GERMAN.value)
    )
    window.worker_combo.setCurrentIndex(window.worker_combo.findData(WorkerMode.FIXED.value))
    window.worker_spin.setValue(3)
    window.stats_box.setChecked(True)
    assert window.dirty and window.save_button.isEnabled() and window.worker_spin.isEnabled()
    assert window.settings_status.text() == "Unsaved changes"
    assert window.save_settings()
    assert window.tabs.tabText(0) == "Umwandeln"
    assert window.start_button.text() == "Starten"
    data = json.loads((tmp_path / SETTINGS_FILE_NAME).read_text())
    assert data["ui_language"] == "de" and data["fixed_workers"] == 3 and data["statistics_enabled"]
    assert not window.dirty
    window.suffix_edit.setText("_ocr")
    window.revert_settings()
    assert window.suffix_edit.text() == "_searchable"


def test_invalid_form_disables_save(qtbot: QtBot, tmp_path: Path) -> None:
    window = make_window(qtbot, tmp_path)
    window.suffix_edit.setText("bad/name")
    assert not window.save_button.isEnabled()
    assert "suffix_invalid" in window.settings_status.text()
    assert window.dirty
    assert not window.save_settings()
    window.suffix_edit.setText("_ocr")
    assert window.suffix_example.text() == "Example: Scan_ocr.pdf"
    for box in window.language_boxes.values():
        box.setChecked(False)
    assert "languages_empty" in window.settings_status.text()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_save_failure_keeps_changes_and_old_file(qtbot: QtBot, tmp_path: Path) -> None:
    SettingsRepository(tmp_path).save(Settings(), None)
    before = (tmp_path / SETTINGS_FILE_NAME).read_bytes()
    window = make_window(qtbot, tmp_path)
    window.suffix_edit.setText("_ocr")
    tmp_path.chmod(0o555)
    try:
        assert not window.save_settings()
    finally:
        tmp_path.chmod(0o755)
    assert window.suffix_edit.text() == "_ocr" and window.dirty
    assert "Move Searchify PDF" in window.message.shown[-1]  # type: ignore[attr-defined]
    assert (tmp_path / SETTINGS_FILE_NAME).read_bytes() == before


def test_save_failure_other_error(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from searchify_pdf.storage import settings_repository

    window = make_window(qtbot, tmp_path)
    window.suffix_edit.setText("_ocr")

    def full(*_: object) -> None:
        raise OSError(28, "No space left")

    monkeypatch.setattr(settings_repository, "atomic_write_bytes", full)
    assert not window.save_settings()
    assert "disk_full" in window.settings_status.text()


def test_read_only_and_malformed_notices(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / SETTINGS_FILE_NAME).write_text("{broken")
    monkeypatch.setattr(SettingsRepository, "is_writable", lambda self: False)
    window = make_window(qtbot, tmp_path)
    assert not window.settings_notice.isHidden()
    text = window.settings_notice.text()
    assert "could not be read" in text and "Move Searchify PDF" in text


def test_stale_settings_reload_and_overwrite(qtbot: QtBot, tmp_path: Path) -> None:
    window = make_window(qtbot, tmp_path)
    other = SettingsRepository(tmp_path)
    other.save(Settings(theme=Theme.DARK), None)
    window.suffix_edit.setText("_ocr")
    window.message = Messages(Std.Reset)
    assert window.save_settings()
    assert window.saved.theme is Theme.DARK and window.suffix_edit.text() == "_searchable"
    fp = other.load().fingerprint
    other.save(Settings(theme=Theme.LIGHT), fp)
    window.suffix_edit.setText("_ocr")
    window.message = Messages(Std.Save)
    assert window.save_settings()
    assert other.load().settings.output_suffix == "_ocr"
    fp = other.load().fingerprint
    other.save(Settings(), fp)
    window.suffix_edit.setText("_x")
    window.message = Messages(Std.Cancel)
    assert not window.save_settings()
    assert window.dirty


def test_close_prompts(qtbot: QtBot, tmp_path: Path) -> None:
    window = make_window(qtbot, tmp_path)
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()  # nothing unsaved
    window.suffix_edit.setText("_ocr")
    for answer, accepted in ((Std.Cancel, False), (Std.Discard, True)):
        window.message = Messages(answer)
        event = QCloseEvent()
        window.closeEvent(event)
        assert event.isAccepted() is accepted
    assert not (tmp_path / SETTINGS_FILE_NAME).exists()  # discard never saves silently
    window.message = Messages(Std.Save)
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
    assert SettingsRepository(tmp_path).load().settings.output_suffix == "_ocr"


def test_close_with_failed_save_stays_open(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from searchify_pdf.storage import settings_repository

    window = make_window(qtbot, tmp_path)
    window.suffix_edit.setText("_ocr")

    def broken(*_: object) -> None:
        raise OSError(5, "I/O")

    monkeypatch.setattr(settings_repository, "atomic_write_bytes", broken)
    window.message = Messages(Std.Save, Std.Ok)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()


def test_close_while_running(qtbot: QtBot, tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    window = make_window(qtbot, tmp_path, FakeEngine(delay=10))
    window.add_paths([src])
    window.start()
    window.message = Messages(Std.No)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted() and window.running
    window.message = Messages(Std.Yes)
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
    qtbot.waitUntil(lambda: not window.running, timeout=20000)


def test_statistics_view_and_reset(qtbot: QtBot, tmp_path: Path) -> None:
    SettingsRepository(tmp_path).save(Settings(statistics_enabled=True), None)
    window = make_window(qtbot, tmp_path)
    assert "unavailable" in window.stats_view.toPlainText()
    window.add_paths([synthetic.scanned_pdf(tmp_path / "a.pdf")])
    run_and_wait(qtbot, window)
    text = window.stats_view.toPlainText()
    assert "Documents: 1" in text and "median" in text and "estimate" in text
    assert "not measured" in text
    window.message = Messages(Std.No)
    window.reset_statistics()
    assert window.stats_repo.load().attempted == 1
    window.message = Messages(Std.Yes)
    window.reset_statistics()
    assert window.stats_repo.load().attempted == 0


def test_statistics_errors(qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from searchify_pdf.storage.statistics import (
        STATS_FILE_NAME,
        StatisticsError,
        StatisticsRepository,
    )

    SettingsRepository(tmp_path).save(Settings(statistics_enabled=True), None)
    (tmp_path / STATS_FILE_NAME).write_text("{bad")
    window = make_window(qtbot, tmp_path)
    assert "json_invalid" in window.stats_view.toPlainText()

    def fail(self: StatisticsRepository) -> None:
        raise StatisticsError("permission_denied")

    monkeypatch.setattr(StatisticsRepository, "reset", fail)
    window.message = Messages(Std.Yes)
    window.reset_statistics()
    assert "permission_denied" in window.stats_view.toPlainText()
    monkeypatch.setattr(StatisticsRepository, "record_batch", lambda *a, **k: "disk_full")
    window.add_paths([synthetic.scanned_pdf(tmp_path / "a.pdf")])
    run_and_wait(qtbot, window)
    assert "Statistics could not be saved: disk_full" in window.summary_label.text()
    assert (tmp_path / "a_searchable.pdf").exists()  # conversion kept despite stats failure


def test_install_launcher(qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    window = make_window(qtbot, tmp_path)
    window.install_launcher()
    assert (tmp_path / "share" / "applications" / "searchify-pdf.desktop").exists()
    assert "Added to the app menu" in window.message.shown[-1]  # type: ignore[attr-defined]
    (tmp_path / "blocked").write_text("file, not a dir")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "blocked"))
    window.install_launcher()
    assert "Could not add launcher" in window.message.shown[-1]  # type: ignore[attr-defined]


def test_themes(qtbot: QtBot, tmp_path: Path) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    assert theme.apply_theme(app, Theme.DARK) is theme.DARK
    assert theme.apply_theme(app, Theme.LIGHT) is theme.LIGHT
    assert theme.apply_theme(app, Theme.SYSTEM) in {theme.LIGHT, theme.DARK}
    assert theme.DARK.accent in theme.stylesheet(theme.DARK)
    window = make_window(qtbot, tmp_path)
    window.theme_combo.setCurrentIndex(window.theme_combo.findData(Theme.DARK.value))
    assert window.save_settings()
    assert theme.DARK.window in app.styleSheet()


def test_engine_label_survives_probe_failure(qtbot: QtBot, tmp_path: Path) -> None:
    class Broken(FakeEngine):
        def capabilities(self) -> Any:
            raise RuntimeError("no engine")

    window = make_window(qtbot, tmp_path, Broken())
    assert "unavailable (no engine)" in window.engine_label.text()


def test_file_open_events_queue_and_start(qtbot: QtBot, tmp_path: Path) -> None:
    window = make_window(qtbot, tmp_path)
    flt = FileOpenFilter(window)
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    assert flt.eventFilter(window, QFileOpenEvent(str(src)))
    assert flt.eventFilter(window, QFileOpenEvent(""))
    qtbot.waitUntil(lambda: not window.running, timeout=20000)
    assert (tmp_path / "a_searchable.pdf").exists()
    assert not flt.eventFilter(window, QCloseEvent())


def test_create_window_drop_launch_uses_saved_settings(qtbot: QtBot, tmp_path: Path) -> None:
    SettingsRepository(tmp_path).save(Settings(output_suffix="_ocr"), None)
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    _app, window = app_module.create_window(
        Settings(output_suffix="_ocr"), [src], tmp_path, lambda: FakeEngine()
    )
    qtbot.addWidget(window)
    assert window.run_overrides is None
    qtbot.waitUntil(lambda: (tmp_path / "a_ocr.pdf").exists(), timeout=20000)
    qtbot.waitUntil(lambda: not window.running, timeout=20000)
    _app, window2 = app_module.create_window(
        Settings(output_suffix="_cli"), [], tmp_path, lambda: FakeEngine()
    )
    qtbot.addWidget(window2)
    assert window2.run_overrides is not None and window2.run_settings().output_suffix == "_cli"
    assert app_module._default_engine().name == "ocrmypdf"


def test_batch_thread_internal_error_and_cancelled_prompts(qtbot: QtBot, tmp_path: Path) -> None:
    class Exploding(FakeEngine):
        def readiness_problem(self, languages: tuple[str, ...]) -> Any:
            raise RuntimeError("kaboom")

    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    thread = BatchThread(Settings(), [src], Exploding(), lambda k, p: Decision(Choice.NO))
    with qtbot.waitSignal(thread.done, timeout=10000):
        thread.start()
    thread.wait()
    assert thread.summary is not None and "kaboom" in thread.summary.statistics_error
    bridge = _PromptBridge(lambda k, p: Decision(Choice.YES))
    decisions = GuiDecisions(bridge, thread.cancel_event)
    thread.cancel()
    assert decisions.existing_output(src, src).choice is Choice.CANCEL  # type: ignore[union-attr]
    bridge.handle("text", {})
    assert bridge.answer.choice is Choice.YES


def test_existing_text_prompt_goes_through_bridge(qtbot: QtBot, tmp_path: Path) -> None:
    from searchify_pdf.domain.settings import ExistingTextPolicy

    SettingsRepository(tmp_path).save(Settings(existing_text_policy=ExistingTextPolicy.ASK), None)
    window = make_window(qtbot, tmp_path)
    payloads: list[dict[str, object]] = []

    def prompter(kind: str, payload: dict[str, object]) -> Decision:
        payloads.append(payload)
        return Decision(Choice.NO)

    window.prompter = prompter
    window.add_paths([synthetic.digital_pdf(tmp_path / "d.pdf")])
    run_and_wait(qtbot, window)
    assert payloads[0]["text_pages"] == 1
    assert window.last_summary is not None and window.last_summary.count(Outcome.PRESERVED) == 1


def test_edge_paths(qtbot: QtBot, tmp_path: Path) -> None:
    from searchify_pdf.domain.jobs import JobEvent, JobState

    window = make_window(qtbot, tmp_path, FakeEngine(delay=0.5))
    window.open_result_folder()  # no summary yet: nothing happens
    window.cancel()  # nothing running: no-op
    empty = tmp_path / "empty"
    empty.mkdir()
    window.add_paths([empty])
    run_and_wait(qtbot, window)
    assert "No PDFs found." in window.summary_label.text()
    window._on_event(JobEvent(99, tmp_path / "x.pdf", JobState.RUNNING))  # unknown job id
    natural = synthetic.scanned_pdf(tmp_path / "Report_searchable.pdf")
    window.add_paths([natural])
    window.start()
    window.add_paths([tmp_path / "later.pdf"])  # queued while running, table untouched
    window.clear_queue()  # ignored while running
    qtbot.waitUntil(lambda: not window.running, timeout=20000)
    details = window.table.item(0, 3).text()
    assert "Name ends like a searchable copy" in details
    window.ui_language_combo.setCurrentIndex(window.ui_language_combo.findData("de"))
    assert window.save_settings()
    assert "Abgeschlossen" in window.summary_label.text()  # summary re-rendered in German
    window._on_done(window.last_summary)  # type: ignore[arg-type]  # no thread attached


def test_failed_job_tooltip_has_engine_detail(qtbot: QtBot, tmp_path: Path) -> None:
    from searchify_pdf.domain.jobs import Reason

    window = make_window(qtbot, tmp_path, FakeEngine(fail=Reason.ENGINE_FAILED))
    window.add_paths([synthetic.scanned_pdf(tmp_path / "a.pdf")])
    run_and_wait(qtbot, window)
    assert "fake failure" in window.table.item(0, 3).toolTip()


def test_file_open_while_running_only_queues(qtbot: QtBot, tmp_path: Path) -> None:
    window = make_window(qtbot, tmp_path, FakeEngine(delay=1))
    flt = FileOpenFilter(window)
    window.add_paths([synthetic.scanned_pdf(tmp_path / "a.pdf")])
    window.start()
    assert flt.eventFilter(window, QFileOpenEvent(str(tmp_path / "b.pdf")))
    assert tmp_path / "b.pdf" in window.queue
    qtbot.waitUntil(lambda: not window.running, timeout=20000)


def test_batch_thread_run_synchronously(tmp_path: Path) -> None:
    src = synthetic.scanned_pdf(tmp_path / "a.pdf")
    thread = BatchThread(Settings(), [src], FakeEngine(), lambda k, p: Decision(Choice.NO))
    plans: list[int] = []
    thread.planned.connect(plans.append)
    thread.run()  # executes the batch in this (traced) thread
    assert thread.summary is not None and thread.summary.count(Outcome.CONVERTED) == 1
    assert plans == [1]

    class Exploding(FakeEngine):
        def readiness_problem(self, languages: tuple[str, ...]) -> Any:
            raise RuntimeError("kaboom")

    broken = BatchThread(Settings(), [src], Exploding(), lambda k, p: Decision(Choice.NO))
    broken.run()
    assert (
        broken.summary is not None and "internal error: kaboom" in broken.summary.statistics_error
    )


def test_gui_decisions_from_worker_thread(qtbot: QtBot, tmp_path: Path) -> None:
    import threading

    bridge = _PromptBridge(lambda kind, payload: Decision(Choice.YES, kind == "text"))
    bridge.request.connect(bridge.handle, Qt.ConnectionType.BlockingQueuedConnection)
    decisions = GuiDecisions(bridge, threading.Event())
    answers: list[Decision | None] = []

    def worker() -> None:
        answers.append(decisions.existing_output(tmp_path / "a.pdf", tmp_path / "b.pdf"))
        answers.append(decisions.existing_text(tmp_path / "a.pdf", 1, 2))

    t = threading.Thread(target=worker)
    t.start()
    qtbot.waitUntil(lambda: len(answers) == 2, timeout=5000)
    t.join()
    assert answers == [Decision(Choice.YES), Decision(Choice.YES, True)]
