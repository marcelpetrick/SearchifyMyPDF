# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Runs a :class:`BatchRunner` off the UI thread and marshals prompts to the UI thread.

Prompts use a ``BlockingQueuedConnection``: the batch thread waits safely while the
UI thread shows the question, so the window stays responsive and prompts are
serialized (VISION §9).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from searchify_pdf import __version__
from searchify_pdf.application.workflow import BatchRunner, Choice, Decision
from searchify_pdf.domain.jobs import BatchSummary, JobEvent
from searchify_pdf.domain.settings import Settings
from searchify_pdf.engines.base import OcrEngine

Prompter = Callable[[str, dict[str, object]], Decision]


class _PromptBridge(QObject):
    request = Signal(str, dict)

    def __init__(self, prompter: Prompter) -> None:
        super().__init__()
        self.prompter = prompter
        self.answer: Decision = Decision(Choice.CANCEL)

    @Slot(str, dict)
    def handle(self, kind: str, payload: dict[str, object]) -> None:
        self.answer = self.prompter(kind, payload)


class GuiDecisions:
    def __init__(self, bridge: _PromptBridge, cancel: threading.Event) -> None:
        self._bridge = bridge
        self._cancel = cancel
        self._lock = threading.Lock()

    def _ask(self, kind: str, payload: dict[str, object]) -> Decision:
        with self._lock:
            if self._cancel.is_set():
                return Decision(Choice.CANCEL)
            self._bridge.request.emit(kind, payload)  # blocks until the UI answered
            return self._bridge.answer

    def existing_output(self, source: Path, destination: Path) -> Decision | None:
        return self._ask("output", {"source": str(source), "destination": str(destination)})

    def existing_text(self, source: Path, text_pages: int, total_pages: int) -> Decision | None:
        return self._ask(
            "text", {"source": str(source), "text_pages": text_pages, "pages": total_pages}
        )


class BatchThread(QThread):
    job_event = Signal(object)  # JobEvent
    planned = Signal(int)  # number of concurrent documents
    done = Signal(object)  # BatchSummary

    def __init__(
        self,
        settings: Settings,
        paths: Sequence[Path],
        engine: OcrEngine,
        prompter: Prompter,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.paths = list(paths)
        self.engine = engine
        self.cancel_event = threading.Event()
        self.bridge = _PromptBridge(prompter)
        self.bridge.request.connect(self.bridge.handle, Qt.ConnectionType.BlockingQueuedConnection)
        self.summary: BatchSummary | None = None
        self._runner: BatchRunner | None = None
        self._planned_sent = False

    def cancel(self) -> None:
        self.cancel_event.set()

    def _on_event(self, event: JobEvent) -> None:
        if not self._planned_sent and self._runner is not None and self._runner.plan is not None:
            self._planned_sent = True
            self.planned.emit(self._runner.plan.documents)
        self.job_event.emit(event)

    def run(self) -> None:
        runner = self._runner = BatchRunner(
            self.settings,
            self.engine,
            decisions=GuiDecisions(self.bridge, self.cancel_event),
            on_event=self._on_event,
            cancel=self.cancel_event,
            version=__version__,
        )
        try:
            summary = runner.run(self.paths)
        except Exception as exc:  # never leave the UI waiting forever
            summary = BatchSummary((), (), 0.0, 1, f"internal error: {exc}")
        self.summary = summary
        self.done.emit(summary)
