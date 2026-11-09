# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Fake engine and decision providers for fast, deterministic workflow tests."""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from searchify_pdf.application.workflow import Choice, Decision
from searchify_pdf.domain.jobs import Reason
from searchify_pdf.engines.base import EngineCapabilities, EngineRequest, EngineResult


class FakeEngine:
    name = "fake"

    def __init__(
        self,
        *,
        fail: Reason | None = None,
        delay: float = 0.0,
        ready: tuple[Reason, str] | None = None,
        writer: Callable[[EngineRequest], None] | None = None,
    ) -> None:
        self.fail = fail
        self.delay = delay
        self.ready = ready
        self.writer = writer
        self.requests: list[EngineRequest] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities("Fake", "1", ("deu", "eng"), True, False)

    def readiness_problem(self, languages: tuple[str, ...]) -> tuple[Reason, str] | None:
        return self.ready

    def run(self, request: EngineRequest, cancel: threading.Event) -> EngineResult:
        with self._lock:
            self.requests.append(request)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            deadline = time.monotonic() + self.delay
            while time.monotonic() < deadline:
                if cancel.wait(0.01):
                    return EngineResult(False, Reason.CANCELLED)
            if self.fail is not None:
                request.output.write_bytes(b"partial garbage")
                return EngineResult(False, self.fail, "fake failure")
            if self.writer is not None:
                self.writer(request)
            else:
                shutil.copyfile(request.source, request.output)
            return EngineResult(True)
        finally:
            with self._lock:
                self.active -= 1


class ScriptedDecisions:
    """Answers prompts from queues and records what was asked."""

    def __init__(
        self, output: list[Decision] | None = None, text: list[Decision] | None = None
    ) -> None:
        self.output = list(output or [])
        self.text = list(text or [])
        self.asked: list[tuple[str, Path]] = []

    def existing_output(self, source: Path, destination: Path) -> Decision | None:
        self.asked.append(("output", source))
        return self.output.pop(0) if self.output else None

    def existing_text(self, source: Path, text_pages: int, total_pages: int) -> Decision | None:
        self.asked.append(("text", source))
        return self.text.pop(0) if self.text else None


YES = Decision(Choice.YES)
NO = Decision(Choice.NO)
CANCEL = Decision(Choice.CANCEL)
YES_ALL = Decision(Choice.YES, apply_to_batch=True)
NO_ALL = Decision(Choice.NO, apply_to_batch=True)
