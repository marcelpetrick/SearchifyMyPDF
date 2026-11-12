# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from searchify_pdf.domain.jobs import Reason
from searchify_pdf.engines import ocrmypdf_engine, worker
from searchify_pdf.engines.base import EngineRequest, OcrMode
from searchify_pdf.engines.ocrmypdf_engine import (
    OcrmypdfEngine,
    kill_process_tree,
    recognition_order,
    worker_command,
)


def _request(tmp_path: Path, mode: OcrMode = OcrMode.PRESERVE_TEXT, **kw: object) -> EngineRequest:
    return EngineRequest(tmp_path / "in.pdf", tmp_path / "out.pdf", ("eng",), mode, **kw)  # type: ignore[arg-type]


def _fake(script: str) -> OcrmypdfEngine:
    return OcrmypdfEngine(command=lambda: [sys.executable, "-c", script])


def test_worker_command_source_and_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    assert worker_command()[1:] == ["-m", "searchify_pdf.engines.worker"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert worker_command() == [sys.executable, worker.WORKER_FLAG]


def test_build_kwargs_modes() -> None:
    base = {"source": "a", "output": "b", "languages": ["eng", "deu"], "deskew": True}
    preserve = worker.build_kwargs({**base, "mode": "preserve_text", "page_jobs": 0})
    assert preserve["skip_text"] and preserve["deskew"] and preserve["jobs"] == 1
    assert preserve["output_type"] == "pdf" and preserve["language"] == ["eng", "deu"]
    assert preserve["use_threads"] is True
    assert "redo_ocr" not in preserve and "force_ocr" not in preserve
    redo = worker.build_kwargs({**base, "mode": "redo_ocr"})
    assert redo["redo_ocr"] and "deskew" not in redo and "force_ocr" not in redo


def test_worker_main_argument_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert worker.main([]) == 1
    assert worker.main(["{bad"]) == 1
    assert worker.main(['{"source": 1}']) == 1
    assert "invalid worker request" in capsys.readouterr().err


def test_worker_main_maps_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    import ocrmypdf
    from ocrmypdf.exceptions import EncryptedPdfError

    req = json.dumps({"source": "a", "output": "b", "languages": ["eng"], "mode": "preserve_text"})
    confined: list[Path] = []
    monkeypatch.setattr(worker, "confine", confined.append)  # never sandbox pytest itself

    def encrypted(**_: object) -> int:
        raise EncryptedPdfError("locked")

    monkeypatch.setattr(ocrmypdf, "ocr", encrypted)
    assert worker.main([req]) == 8

    def other(**_: object) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(ocrmypdf, "ocr", other)
    assert worker.main([req]) == worker.OTHER_ERROR
    monkeypatch.setattr(ocrmypdf, "ocr", lambda **_: 0)
    assert worker.main([req]) == 0
    assert confined == [Path("b")] * 3  # confined before every conversion


def test_redo_drops_deskew_with_note(tmp_path: Path) -> None:
    payload, notes = OcrmypdfEngine().build_request_json(
        _request(tmp_path, OcrMode.REDO_OCR, deskew=True)
    )
    assert json.loads(payload)["deskew"] is False
    assert notes == (Reason.DESKEW_DISABLED_FOR_REDO,)
    payload, notes = OcrmypdfEngine().build_request_json(_request(tmp_path, deskew=True))
    assert json.loads(payload)["deskew"] is True and notes == ()


@pytest.mark.parametrize(
    ("code", "mode", "reason"),
    [
        (0, OcrMode.PRESERVE_TEXT, Reason.OK),
        (2, OcrMode.PRESERVE_TEXT, Reason.INVALID_PDF),
        (2, OcrMode.REDO_OCR, Reason.REDO_UNSUPPORTED),
        (8, OcrMode.PRESERVE_TEXT, Reason.ENCRYPTED),
        (3, OcrMode.REDO_OCR, Reason.ENGINE_MISSING),
        (99, OcrMode.PRESERVE_TEXT, Reason.ENGINE_FAILED),
    ],
)
def test_exit_code_mapping(tmp_path: Path, code: int, mode: OcrMode, reason: Reason) -> None:
    result = _fake(f"import sys; print('diag'); sys.exit({code})").run(
        _request(tmp_path, mode), threading.Event()
    )
    assert result.ok is (code == 0)
    assert result.reason is reason
    if code:
        assert "diag" in result.detail


def test_spawn_failure(tmp_path: Path) -> None:
    engine = OcrmypdfEngine(command=lambda: [str(tmp_path / "missing-binary")])
    assert engine.run(_request(tmp_path), threading.Event()).reason is Reason.ENGINE_MISSING


CHILD_SCRIPT = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
print(child.pid, flush=True)
time.sleep(60)
"""


def test_cancel_kills_whole_process_tree(tmp_path: Path) -> None:
    before = {p.pid for p in psutil.Process().children(recursive=True)}
    cancel = threading.Event()
    engine = _fake(CHILD_SCRIPT)
    results = []
    thread = threading.Thread(target=lambda: results.append(engine.run(_request(tmp_path), cancel)))
    thread.start()
    deadline = time.monotonic() + 20
    spawned: set[int] = set()
    while time.monotonic() < deadline and len(spawned) < 2:
        spawned = {p.pid for p in psutil.Process().children(recursive=True)} - before
        time.sleep(0.05)
    assert len(spawned) >= 2
    cancel.set()
    thread.join(20)
    assert results[0].reason is Reason.CANCELLED
    time.sleep(0.2)
    alive = [
        pid
        for pid in spawned
        if psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    ]
    assert alive == []


def test_timeout(tmp_path: Path) -> None:
    ticks = iter([0.0, 0.0, 5000.0, 5000.0, 5000.0])
    engine = OcrmypdfEngine(
        command=lambda: [sys.executable, "-c", "import time; time.sleep(60)"],
        clock=lambda: next(ticks),
    )
    result = engine.run(_request(tmp_path, timeout_seconds=1.0), threading.Event())
    assert result.reason is Reason.TIMEOUT


def test_kill_escalates_to_sigkill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocrmypdf_engine, "TERMINATE_GRACE_SECONDS", 0.2)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('r', flush=True); time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    assert proc.stdout is not None
    proc.stdout.readline()
    kill_process_tree(proc)
    assert proc.returncode is not None
    kill_process_tree(proc)  # already finished: no-op


def test_readiness_and_capabilities() -> None:
    engine = OcrmypdfEngine()
    caps = engine.capabilities()
    assert "OCRmyPDF" in caps.name and caps.supports_redo and not caps.redo_supports_deskew
    assert {"eng", "deu"} <= set(caps.available_languages)
    assert engine.readiness_problem(("eng", "deu")) is None
    assert engine.readiness_problem(("eng", "xyz")) == (Reason.ENGINE_MISSING, "xyz")
    missing = OcrmypdfEngine(tesseract="definitely-not-tesseract")
    assert missing.readiness_problem(("eng",)) == (Reason.ENGINE_MISSING, "tesseract")
    assert "missing" in missing.capabilities().name


def test_tesseract_probe_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> None:
        raise subprocess.TimeoutExpired("tesseract", 30)

    monkeypatch.setattr(ocrmypdf_engine.subprocess, "run", boom)
    assert OcrmypdfEngine().readiness_problem(("eng",)) == (Reason.ENGINE_MISSING, "tesseract")


def test_tesseract_empty_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ocrmypdf_engine.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="", stderr=""),
    )
    assert OcrmypdfEngine()._tesseract_info == ("unknown", ())


def test_english_is_recognised_last(tmp_path: Path) -> None:
    """eng before deu drops umlauts ("für" → "fur"); see test_ocr_quality.py."""
    assert recognition_order(("eng", "deu")) == ("deu", "eng")
    assert recognition_order(("eng", "fra", "deu")) == ("fra", "deu", "eng")
    assert recognition_order(("deu",)) == ("deu",) and recognition_order(("eng",)) == ("eng",)
    request = EngineRequest(
        tmp_path / "a.pdf", tmp_path / "b.pdf", ("eng", "deu"), OcrMode.REDO_OCR
    )
    payload, _ = OcrmypdfEngine().build_request_json(request)
    assert json.loads(payload)["languages"] == ["deu", "eng"]
