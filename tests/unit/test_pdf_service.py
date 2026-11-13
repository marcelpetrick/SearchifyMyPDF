# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Sandboxed PDF service (#13, ADR 0017): protocol, hostile answers, crashes, timeouts."""

from __future__ import annotations

import io
import json
import os
import struct
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pikepdf
import pytest

from searchify_pdf.domain.jobs import Reason
from searchify_pdf.engines import pdf_inspect, pdf_ops, pdf_service
from searchify_pdf.engines.pdf_inspect import PdfInspectionError
from searchify_pdf.engines.pdf_service import PdfService, ProtocolError, ServiceError
from tests import synthetic


def frame(header: dict[str, Any], blobs: list[bytes] = ()) -> bytes:  # type: ignore[assignment]
    stream = io.BytesIO()
    pdf_service.write_frame(stream, header, list(blobs))
    return stream.getvalue()


def test_frames_round_trip() -> None:
    stream = io.BytesIO(frame({"op": "x", "args": {"a": 1}}, [b"one", b""]))
    header, blobs = pdf_service.read_frame(stream)
    assert header == {"op": "x", "args": {"a": 1}, "blobs": 2}
    assert blobs == [b"one", b""]


@pytest.mark.parametrize(
    "data",
    [
        b"",  # closed
        b"\x00\x00",  # truncated length
        struct.pack(">I", pdf_service.MAX_HEADER + 1),
        struct.pack(">I", 3) + b"{x}",
        struct.pack(">I", 2) + b"[]",
        struct.pack(">I", 13) + b'{"blobs": -1}',
        struct.pack(">I", 15) + b'{"blobs": "1"}x',
        struct.pack(">I", 12) + b'{"blobs": 1}' + struct.pack(">Q", pdf_service.MAX_BLOB + 1),
        struct.pack(">I", 12) + b'{"blobs": 1}' + struct.pack(">Q", 5) + b"abc",
    ],
)
def test_hostile_or_broken_frames_are_rejected(data: bytes) -> None:
    with pytest.raises((ProtocolError, struct.error)):
        pdf_service.read_frame(io.BytesIO(data))


def test_serve_answers_until_the_pipe_closes(tmp_path: Path) -> None:
    pdf = synthetic.scanned_pdf(tmp_path / "s.pdf").read_bytes()
    requests = (
        frame({"op": "count_pages", "args": {"password": ""}}, [pdf])
        + frame({"op": "nope", "args": {}})
        + frame({"op": 3, "args": {}})
        + frame({"op": "count_pages", "args": {}}, [pdf])
    )
    out = io.BytesIO()
    assert pdf_service.serve(io.BytesIO(requests), out) == 0
    out.seek(0)
    answers = [pdf_service.read_frame(out)[0] for _ in range(4)]
    assert answers[0] == {"ok": True, "result": {"value": 1}, "blobs": 0}
    assert [a["reason"] for a in answers[1:]] == ["engine_failed"] * 3
    assert "unknown operation" in answers[1]["detail"]
    assert answers[2]["detail"] == "malformed request"
    assert "bad request" in answers[3]["detail"]


def test_operations_map_parser_failures(tmp_path: Path) -> None:
    with pytest.raises(pdf_ops.OpError) as info:
        pdf_ops.dispatch("count_pages", {"password": ""}, [b"not a pdf"])
    assert info.value.reason is Reason.INVALID_PDF
    locked = synthetic.encrypted_pdf(tmp_path / "e.pdf").read_bytes()
    with pytest.raises(pdf_ops.OpError) as info:
        pdf_ops.dispatch("count_pages", {"password": "wrong"}, [locked])
    assert info.value.reason is Reason.WRONG_PASSWORD
    assert str(pdf_ops.OpError(Reason.OK)) == "ok"
    assert pdf_ops.has_marker(b"junk") is False


def test_render_returns_text_and_png(tmp_path: Path) -> None:
    pdf = synthetic.digital_pdf(tmp_path / "t.pdf").read_bytes()
    result, images = pdf_ops.dispatch("render", {"password": "", "pages": [0], "dpi": 50}, [pdf])
    assert len(result["texts"]) == 1 and result["texts"][0].strip()
    assert images[0].startswith(b"\x89PNG")


class Scripted:
    """A fake service process: ``python -c`` with a script that answers in some way."""

    def __init__(self, tmp_path: Path, body: str) -> None:
        self.script = tmp_path / "fake_service.py"
        self.script.write_text(textwrap.dedent("""
                import json, struct, sys, time
                inp, out = sys.stdin.buffer, sys.stdout.buffer
                def answer(header, blobs=()):
                    data = json.dumps({**header, "blobs": len(blobs)}).encode()
                    out.write(struct.pack(">I", len(data)) + data)
                    for blob in blobs:
                        out.write(struct.pack(">Q", len(blob)) + blob)
                    out.flush()
                size, = struct.unpack(">I", inp.read(4))
                request = json.loads(inp.read(size))
                for _ in range(request["blobs"]):
                    n, = struct.unpack(">Q", inp.read(8))
                    inp.read(n)
                """) + textwrap.dedent(body))

    def __call__(self) -> list[str]:
        return [sys.executable, str(self.script)]


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ('answer({"ok": False, "reason": "wrong_password", "detail": "x"})', "wrong_password"),
        ('answer({"ok": False, "reason": "made-up"})', "engine_failed"),
        ('answer({"ok": True, "result": [1]})', "engine_failed"),
        ("sys.exit(3)", "invalid_pdf"),
        ("out.write(b'garbage!'); out.flush()", "invalid_pdf"),
    ],
)
def test_client_distrusts_answers(tmp_path: Path, body: str, reason: str) -> None:
    service = PdfService(Scripted(tmp_path, body))
    try:
        with pytest.raises(ServiceError) as info:
            service.call("count_pages", {}, [b"%PDF"])
        assert info.value.reason.value == reason
    finally:
        service.close()


def test_a_hanging_service_is_killed_and_replaced(tmp_path: Path) -> None:
    hang = Scripted(tmp_path, "time.sleep(60)")
    service = PdfService(hang, timeout_seconds=0.5)
    try:
        with pytest.raises(ServiceError) as info:
            service.call("count_pages", {}, [b"%PDF"])
        assert info.value.reason is Reason.TIMEOUT
        hang.script.write_text(hang.script.read_text().replace("time.sleep(60)", ""))
        good = 'answer({"ok": True, "result": {"value": 7}})'
        hang.script.write_text(hang.script.read_text() + good)
        assert service.call("count_pages", {}, [b"%PDF"]) == ({"value": 7}, [])
    finally:
        service.close()


def test_a_service_that_cannot_start(tmp_path: Path) -> None:
    service = PdfService(lambda: [str(tmp_path / "missing-exe")])
    with pytest.raises(ServiceError) as info:
        service.call("count_pages", {}, [])
    assert info.value.reason is Reason.ENGINE_MISSING
    service.close()


def test_service_command(monkeypatch: pytest.MonkeyPatch) -> None:
    assert pdf_service.service_command()[1:] == ["-m", "searchify_pdf.engines.pdf_service"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert pdf_service.service_command() == [sys.executable, pdf_service.SERVICE_FLAG]


def test_shared_service_is_one_per_process() -> None:
    assert pdf_service.shared() is pdf_service.shared()


def test_entry_point_routes_the_service_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from searchify_pdf import __main__ as entry

    monkeypatch.setattr(pdf_service, "main", lambda: 42)
    assert entry.main([pdf_service.SERVICE_FLAG]) == 42


class Answers:
    """A backend that returns fixed (possibly hostile) answers."""

    def __init__(self, result: dict[str, Any], blobs: list[bytes] = ()) -> None:  # type: ignore[assignment]
        self.result, self.blobs = result, list(blobs)

    def call(self, op: str, args: dict[str, Any], blobs: list[bytes]) -> Any:
        return self.result, self.blobs


@pytest.mark.parametrize(
    "result",
    [
        {"value": {"page_count": 1}},
        {"value": {"page_count": "x", "pages_with_text": [], "protection": None}},
        {
            "value": {
                "page_count": 1,
                "pages_with_text": [False],
                "protection": {"owner": True},
                "signed": False,
                "marker": False,
            }
        },
        {"value": None},
    ],
)
def test_malformed_inspection_results_are_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result: dict[str, Any]
) -> None:
    path = synthetic.scanned_pdf(tmp_path / "s.pdf")
    monkeypatch.setattr(pdf_inspect, "backend", lambda: Answers(result))
    with pytest.raises(PdfInspectionError) as info:
        pdf_inspect.inspect_pdf(path)
    assert info.value.reason is Reason.INVALID_PDF


@pytest.mark.parametrize("value", ["3", True, None])
def test_malformed_page_counts_fail_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: Any
) -> None:
    path = synthetic.scanned_pdf(tmp_path / "s.pdf")
    monkeypatch.setattr(pdf_inspect, "backend", lambda: Answers({"value": value}))
    with pytest.raises(PdfInspectionError) as info:
        pdf_inspect.count_pages(path)
    assert info.value.reason is Reason.VALIDATION_FAILED


def test_missing_documents_and_renderings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = synthetic.scanned_pdf(tmp_path / "s.pdf")
    monkeypatch.setattr(pdf_inspect, "backend", lambda: Answers({}))
    with pytest.raises(PdfInspectionError) as info:
        pdf_inspect.add_marker(path, "1")
    assert info.value.reason is Reason.VALIDATION_FAILED
    with pytest.raises(PdfInspectionError):
        pdf_inspect.render_pages(path, "", [0], 50)
    monkeypatch.setattr(pdf_inspect, "backend", lambda: Answers({"texts": ["a"]}, [b"p", b"q"]))
    with pytest.raises(PdfInspectionError):
        pdf_inspect.render_pages(path, "", [0], 50)


def test_unreadable_source_paths(tmp_path: Path) -> None:
    with pytest.raises(PdfInspectionError) as info:
        pdf_inspect.count_pages(tmp_path / "missing.pdf")
    assert info.value.reason is Reason.NOT_FOUND
    with pytest.raises(PdfInspectionError) as info:
        pdf_inspect.count_pages(tmp_path)  # a folder
    assert info.value.reason in {Reason.INVALID_PDF, Reason.UNREADABLE}


def test_in_process_backend_maps_errors() -> None:
    with pytest.raises(ServiceError) as info:
        pdf_inspect.InProcess().call("nope", {}, [])
    assert info.value.reason is Reason.ENGINE_FAILED


def test_passwords_and_documents_round_trip_through_the_real_service(tmp_path: Path) -> None:
    locked = synthetic.encrypted_pdf(tmp_path / "e.pdf")
    info = pdf_inspect.inspect_pdf(locked, "secret")
    assert info.protection is not None and info.page_count >= 1
    plain = tmp_path / "plain.pdf"
    pdf_inspect.decrypt_copy(locked, "secret", plain)
    pdf_inspect.add_marker(plain, "9.9.9")
    assert pdf_inspect.has_marker(plain)
    again = tmp_path / "again.pdf"
    pdf_inspect.encrypt_like(plain, again, info.protection)
    with pikepdf.open(again, password="secret") as pdf:
        assert pdf.is_encrypted and pdf.docinfo["/SearchifyPDF"] == "9.9.9"


CHILD = textwrap.dedent("""
    import sys
    from searchify_pdf.engines import pdf_service
    sys.argv = ["x"]
    raise SystemExit(pdf_service.main())
    """)


@pytest.mark.skipif(sys.platform != "linux", reason="Landlock is a Linux feature")
def test_the_real_service_is_sandboxed(tmp_path: Path) -> None:
    pdf = synthetic.scanned_pdf(tmp_path / "s.pdf").read_bytes()
    env = {k: v for k, v in os.environ.items() if k != "SEARCHIFY_PDF_SANDBOX"}
    env["TMPDIR"] = str(tmp_path)
    done = subprocess.run(
        [sys.executable, "-c", CHILD],
        input=frame({"op": "count_pages", "args": {"password": ""}}, [pdf]),
        capture_output=True,
        env=env,
        timeout=120,
        check=True,
    )
    header, _ = pdf_service.read_frame(io.BytesIO(done.stdout))
    assert header["result"] == {"value": 1}
    report = done.stderr.decode().splitlines()[0]
    assert report.startswith("sandbox: ")
    if "landlock" in report:
        assert "reads" in report and "seccomp" in report
    assert json.dumps(header)  # the answer is plain JSON
