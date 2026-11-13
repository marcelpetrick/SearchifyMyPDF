# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Sandboxed PDF service: parses documents for the application in a child process (#13).

The application never parses a PDF itself. It reads the bytes and sends them over a
pipe to one long-lived service process, which runs :mod:`searchify_pdf.engines.pdf_ops`
and answers with plain values and bytes. The service sandboxes itself before the first
request (ADR 0017): it may not write anywhere but its private temporary folder, may
read only the runtime, and has no network. A parser exploit therefore can't touch the
user's files or the network, and a parser crash or hang costs one document instead of
the application: the client kills a service that overruns its time limit and starts a
fresh one for the next request.

Frames on both pipes: a 4-byte big-endian header length, a JSON header, then for each
of the header's ``blobs`` an 8-byte length and the bytes. The client treats every
answer as untrusted: sizes are bounded and types are checked, nothing is unpickled.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

from searchify_pdf.domain.jobs import Reason

SERVICE_FLAG = "--searchify-pdf-service"
MAX_HEADER = 16 * 1024 * 1024
MAX_BLOB = 4 * 1024 * 1024 * 1024
MAX_BLOBS = 64
DEFAULT_TIMEOUT_SECONDS = 300.0

Reply = tuple[dict[str, Any], list[bytes]]


class ServiceError(Exception):
    """The operation failed; ``reason`` is a stable code, ``detail`` diagnostic text."""

    def __init__(self, reason: Reason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


class ProtocolError(Exception):
    pass


def _read_exactly(stream: IO[bytes], size: int) -> bytes:
    chunks, remaining = [], size
    while remaining:
        chunk = stream.read(min(remaining, 1 << 20))
        if not chunk:
            raise ProtocolError("connection closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def write_frame(stream: IO[bytes], header: dict[str, Any], blobs: list[bytes]) -> None:
    data = json.dumps({**header, "blobs": len(blobs)}).encode()
    stream.write(struct.pack(">I", len(data)) + data)
    for blob in blobs:
        stream.write(struct.pack(">Q", len(blob)))
        stream.write(blob)
    stream.flush()


def read_frame(stream: IO[bytes]) -> Reply:
    (size,) = struct.unpack(">I", _read_exactly(stream, 4))
    if size > MAX_HEADER:
        raise ProtocolError(f"header of {size} bytes")
    try:
        header = json.loads(_read_exactly(stream, size))
    except ValueError as exc:
        raise ProtocolError(f"bad header: {exc}") from exc
    if not isinstance(header, dict):
        raise ProtocolError("header is not an object")
    count = header.get("blobs")
    if not isinstance(count, int) or not 0 <= count <= MAX_BLOBS:
        raise ProtocolError(f"bad blob count {count!r}")
    blobs = []
    for _ in range(count):
        (length,) = struct.unpack(">Q", _read_exactly(stream, 8))
        if length > MAX_BLOB:
            raise ProtocolError(f"blob of {length} bytes")
        blobs.append(_read_exactly(stream, length))
    return header, blobs


def service_command() -> list[str]:
    """Command that starts the service without relaunching the GUI (frozen app too)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, SERVICE_FLAG]
    return [sys.executable, "-m", "searchify_pdf.engines.pdf_service"]


class PdfService:
    """Client side: one service process, started on first use, one request at a time."""

    def __init__(
        self,
        command: Callable[[], list[str]] = service_command,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._command = command
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._workdir: tempfile.TemporaryDirectory[str] | None = None

    def _start(self) -> subprocess.Popen[bytes]:
        self._workdir = tempfile.TemporaryDirectory(
            prefix="searchify-pdf-", ignore_cleanup_errors=True
        )
        env = dict(os.environ)
        for name in ("TMPDIR", "TEMP", "TMP"):
            env[name] = self._workdir.name
        return subprocess.Popen(
            self._command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )

    def call(self, op: str, args: dict[str, Any], blobs: list[bytes]) -> Reply:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._stop()
                try:
                    self._process = self._start()
                except OSError as exc:
                    raise ServiceError(Reason.ENGINE_MISSING, f"PDF service: {exc}") from exc
            process = self._process
            if process.stdin is None or process.stdout is None:  # pragma: no cover - PIPE
                raise ServiceError(Reason.ENGINE_FAILED, "PDF service has no pipes")
            timer = threading.Timer(self.timeout_seconds, process.kill)
            timer.start()
            try:
                write_frame(process.stdin, {"op": op, "args": args}, blobs)
                header, answer = read_frame(process.stdout)
            except (OSError, ProtocolError, struct.error) as exc:
                timed_out = not timer.is_alive()
                self._stop()
                if timed_out:
                    raise ServiceError(Reason.TIMEOUT, "PDF service took too long") from exc
                raise ServiceError(Reason.INVALID_PDF, f"PDF service stopped: {exc}") from exc
            finally:
                timer.cancel()
        if header.get("ok") is True and isinstance(header.get("result"), dict):
            return header["result"], answer
        try:
            reason = Reason(str(header.get("reason")))
        except ValueError:
            reason = Reason.ENGINE_FAILED
        raise ServiceError(reason, str(header.get("detail", ""))[:2000])

    def _stop(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    with contextlib.suppress(OSError):
                        stream.close()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if self._workdir is not None:
            self._workdir.cleanup()
            self._workdir = None

    def close(self) -> None:
        """End the service (it exits on end of input) and remove its folder."""
        with self._lock:
            self._stop()


def _coverage_data_dirs() -> list[Path]:
    from searchify_pdf.engines.worker import _coverage_data_dirs as dirs

    return dirs()


def confine() -> None:
    """Sandbox the service before it reads its first document."""
    from searchify_pdf.engines import sandbox

    os.chdir(tempfile.gettempdir())  # the user's working directory stays out of reach
    report = sandbox.apply(
        [Path(tempfile.gettempdir()), *_coverage_data_dirs()],
        [Path(os.devnull)],
        readable_dirs=sandbox.runtime_read_dirs(),
    )
    print(report.describe(), file=sys.stderr, flush=True)


def serve(inp: IO[bytes], out: IO[bytes]) -> int:
    """Answer requests until the client closes the pipe."""
    from searchify_pdf.engines import pdf_ops

    while True:
        try:
            header, blobs = read_frame(inp)
        except ProtocolError:
            return 0
        op, args = header.get("op"), header.get("args")
        try:
            if not isinstance(op, str) or not isinstance(args, dict):
                raise pdf_ops.OpError(Reason.ENGINE_FAILED, "malformed request")
            result, answer = pdf_ops.dispatch(op, args, blobs)
        except pdf_ops.OpError as exc:
            write_frame(out, {"ok": False, "reason": exc.reason.value, "detail": exc.detail}, [])
        else:
            write_frame(out, {"ok": True, "result": result}, answer)


def main() -> int:
    # load the native parsers before the sandbox narrows what may be read
    import pikepdf  # noqa: F401
    import PIL.PngImagePlugin  # noqa: F401
    import pypdfium2  # noqa: F401

    # Answers go to a private copy of stdout; anything else that writes to stdout (a
    # native library, a warning) lands on stderr and can't corrupt the protocol.
    answers = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    confine()
    with answers:
        return serve(sys.stdin.buffer, answers)


_shared: PdfService | None = None
_shared_lock = threading.Lock()


def shared() -> PdfService:
    """The application's service, started on first use and ended at exit."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = PdfService()
            atexit.register(_shared.close)
        return _shared


if __name__ == "__main__":
    raise SystemExit(main())
