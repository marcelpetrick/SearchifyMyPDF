# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""OCRmyPDF + Tesseract adapter.

Each conversion runs in its own child process (own session / process group) so that
cancellation and timeouts terminate OCRmyPDF *and* its Tesseract children cleanly
(ADR 0003). The adapter maps OCRmyPDF exit codes to stable reason codes.

Existing-text handling (VISION §4.1):

* ``PRESERVE_TEXT`` → ``--skip-text``: pages with text are kept as they are, image-only
  pages are OCRed. Mixed pages (digital text plus scanned regions) are treated as text
  pages, i.e. kept unchanged — a documented limitation.
* ``REDO_OCR`` → ``--redo-ocr``: replaces the previous invisible OCR layer while keeping
  visible and vector content. It never falls back to ``--force-ocr`` rasterization.
  Deskew is incompatible with redo and is dropped with a visible note.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence

import psutil

from searchify_pdf.domain.jobs import Reason
from searchify_pdf.engines.base import (
    EngineCapabilities,
    EngineRequest,
    EngineResult,
    OcrMode,
    TextChecker,
)
from searchify_pdf.engines.worker import WORKER_FLAG

EXIT_REASONS: dict[int, Reason] = {
    1: Reason.ENGINE_FAILED,  # bad arguments
    2: Reason.INVALID_PDF,  # input file
    3: Reason.ENGINE_MISSING,  # missing dependency
    4: Reason.VALIDATION_FAILED,  # invalid output pdf
    5: Reason.PERMISSION_DENIED,  # file access error
    7: Reason.ENGINE_FAILED,  # child process error
    8: Reason.ENCRYPTED,
    9: Reason.ENGINE_FAILED,  # invalid config
    15: Reason.ENGINE_FAILED,
    130: Reason.CANCELLED,
}
POLL_SECONDS = 0.1
TERMINATE_GRACE_SECONDS = 3.0
MAX_DETAIL_CHARS = 2000


def recognition_order(languages: Sequence[str]) -> tuple[str, ...]:
    """The configured languages with English last.

    Tesseract tries the models in the given order. The English model has no umlauts, so
    with ``eng+deu`` it drops them on lines it attributes to English ("für" → "fur");
    ``deu+eng`` reads German text correctly without losing anything on English text
    (docs/benchmarks.md "Recognition quality", gated by tests/integration/test_ocr_quality.py).
    """
    return tuple(lang for lang in languages if lang != "eng") + tuple(
        lang for lang in languages if lang == "eng"
    )


def worker_command() -> list[str]:
    """Command prefix that starts an engine worker without relaunching the GUI."""
    if getattr(sys, "frozen", False):
        return [sys.executable, WORKER_FLAG]
    return [sys.executable, "-m", "searchify_pdf.engines.worker"]


def kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Terminate the worker and all of its children; escalate to kill after a grace period."""
    if process.poll() is not None:
        return
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        return
    try:  # pragma: no cover - exercised on Windows/macOS runners only
        parent = psutil.Process(process.pid)
        procs = [*parent.children(recursive=True), parent]
    except psutil.NoSuchProcess:  # pragma: no cover
        return
    for proc in procs:  # pragma: no cover
        with contextlib.suppress(psutil.NoSuchProcess):
            proc.terminate()
    _, alive = psutil.wait_procs(procs, timeout=TERMINATE_GRACE_SECONDS)  # pragma: no cover
    for proc in alive:  # pragma: no cover
        with contextlib.suppress(psutil.NoSuchProcess):
            proc.kill()


class OcrmypdfEngine:
    name = "ocrmypdf"

    def __init__(
        self,
        *,
        command: Callable[[], list[str]] = worker_command,
        tesseract: str = "tesseract",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._command = command
        self._tesseract = tesseract
        self._clock = clock

    @functools.cached_property
    def _tesseract_info(self) -> tuple[str, tuple[str, ...]]:
        exe = shutil.which(self._tesseract)
        if exe is None:
            return "", ()
        try:
            version = subprocess.run(
                [exe, "--version"], capture_output=True, text=True, timeout=30, check=False
            )
            langs = subprocess.run(
                [exe, "--list-langs"], capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return "", ()
        first = (version.stdout or version.stderr).strip().splitlines()
        version_text = first[0].removeprefix("tesseract ").strip() if first else "unknown"
        languages = tuple(
            sorted(
                line.strip()
                for line in langs.stdout.splitlines()[1:]
                if line.strip() and line.strip() != "osd"
            )
        )
        return version_text, languages

    def capabilities(self) -> EngineCapabilities:
        import ocrmypdf

        tess_version, languages = self._tesseract_info
        return EngineCapabilities(
            name=f"OCRmyPDF {ocrmypdf.__version__} / Tesseract {tess_version or 'missing'}",
            version=str(ocrmypdf.__version__),
            available_languages=languages,
            supports_redo=True,
            redo_supports_deskew=False,
        )

    def text_checker(self, languages: tuple[str, ...]) -> TextChecker:
        from searchify_pdf.engines.text_check import TesseractTextChecker

        return TesseractTextChecker(languages, tesseract=self._tesseract)

    def readiness_problem(self, languages: Sequence[str]) -> tuple[Reason, str] | None:
        version, available = self._tesseract_info
        if not version:
            return Reason.ENGINE_MISSING, "tesseract"
        missing = [lang for lang in languages if lang not in available]
        if missing:
            return Reason.ENGINE_MISSING, "+".join(missing)
        return None

    def build_request_json(self, request: EngineRequest) -> tuple[str, tuple[Reason, ...]]:
        notes: tuple[Reason, ...] = ()
        deskew = request.deskew
        if request.mode is OcrMode.REDO_OCR and deskew:
            deskew = False
            notes = (Reason.DESKEW_DISABLED_FOR_REDO,)
        payload = {
            "source": str(request.source),
            "output": str(request.output),
            "languages": list(recognition_order(request.languages)),
            "mode": request.mode.value,
            "deskew": deskew,
            "rotate_pages": request.rotate_pages,
            "page_jobs": request.page_jobs,
        }
        return json.dumps(payload), notes

    def run(self, request: EngineRequest, cancel: threading.Event) -> EngineResult:
        payload, notes = self.build_request_json(request)
        env = dict(os.environ)
        env["OMP_THREAD_LIMIT"] = "1"  # Tesseract threads share the document budget
        with tempfile.TemporaryFile() as log:
            try:
                process = subprocess.Popen(
                    [*self._command(), payload],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    start_new_session=(os.name == "posix"),
                )
            except OSError as exc:
                return EngineResult(False, Reason.ENGINE_MISSING, str(exc), notes)
            deadline = self._clock() + request.timeout_seconds
            outcome: Reason | None = None
            while process.poll() is None:
                if cancel.is_set():
                    outcome = Reason.CANCELLED
                elif self._clock() > deadline:
                    outcome = Reason.TIMEOUT
                if outcome is not None:
                    kill_process_tree(process)
                    break
                cancel.wait(POLL_SECONDS)
            log.seek(0)
            detail = log.read().decode("utf-8", "replace")[-MAX_DETAIL_CHARS:].strip()
        if outcome is not None:
            return EngineResult(False, outcome, detail, notes)
        code = process.returncode
        if code == 0:
            return EngineResult(True, Reason.OK, "", notes)
        reason = EXIT_REASONS.get(code, Reason.ENGINE_FAILED)
        if request.mode is OcrMode.REDO_OCR and reason in {
            Reason.ENGINE_FAILED,
            Reason.INVALID_PDF,
        }:
            reason = Reason.REDO_UNSUPPORTED
        return EngineResult(False, reason, f"exit code {code}: {detail}", notes)
