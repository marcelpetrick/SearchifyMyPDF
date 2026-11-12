# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""OCR worker sandbox (#13, ADR 0016).

The pytest process itself is never sandboxed: the logic runs against a fake libc here,
and the real kernel restrictions are exercised in a child process.
"""

from __future__ import annotations

import ctypes
import os
import struct
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from searchify_pdf.engines import sandbox, worker
from searchify_pdf.engines.sandbox import SandboxReport


class FakeLibc:
    """Answers the Landlock syscalls and prctl like a kernel with ``abi`` would."""

    def __init__(self, abi: int = 4, fail: str = "") -> None:
        self.abi, self.fail = abi, fail
        self.calls: list[tuple[Any, ...]] = []
        # plain functions (not bound methods), so the code can set ``restype`` on them
        self.syscall = lambda *args: self._syscall(*args)
        self.prctl = lambda *args: self._prctl(*args)

    def _syscall(self, number: int, *args: Any) -> int:
        self.calls.append((number, *args))
        if number == sandbox._SYS_LANDLOCK_CREATE_RULESET:
            if args[2] == sandbox._CREATE_RULESET_VERSION:
                return self.abi
            if self.fail == "create":
                return -1
            self.attr = bytes(args[0].raw)
            return os.open(os.devnull, os.O_RDONLY)
        if number == sandbox._SYS_LANDLOCK_ADD_RULE:
            self.rules = [*getattr(self, "rules", []), struct.unpack("<Qi", args[2].raw)[0]]
            return -1 if self.fail == "rule" else 0
        return -1 if self.fail == "restrict" else 0

    def _prctl(self, option: int, *args: Any) -> int:
        self.calls.append(("prctl", option))
        if option == sandbox._PR_SET_NO_NEW_PRIVS:
            return -1 if self.fail == "nnp" else 0
        return -1 if self.fail == "seccomp" else 0


@pytest.fixture
def linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(sandbox.DISABLE_ENV, raising=False)
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandbox.platform, "machine", lambda: "x86_64")


def use(monkeypatch: pytest.MonkeyPatch, libc: FakeLibc) -> FakeLibc:
    monkeypatch.setattr(sandbox, "_libc", lambda: libc)
    return libc


def test_rights_grow_with_the_abi() -> None:
    assert sandbox.write_rights(1) & sandbox.FS_REFER == 0
    assert sandbox.write_rights(2) & sandbox.FS_REFER
    assert sandbox.write_rights(2) & sandbox.FS_TRUNCATE == 0
    assert sandbox.write_rights(3) & sandbox.FS_TRUNCATE
    assert sandbox.file_rights(2) == sandbox.FS_WRITE_FILE
    assert sandbox.file_rights(3) == sandbox.FS_WRITE_FILE | sandbox.FS_TRUNCATE
    for abi in (1, 3):  # reading and executing are never restricted
        assert sandbox.write_rights(abi) & 0b1101 == 0


def test_seccomp_program_jumps_stay_inside_and_end_in_returns() -> None:
    program = sandbox.seccomp_program(0xC000003E, 41)
    instructions = [struct.unpack("<HBBI", program[i : i + 8]) for i in range(0, len(program), 8)]
    assert len(instructions) == 11
    for index, (code, jt, jf, _) in enumerate(instructions):
        if code in (sandbox._JEQ_K, sandbox._JGE_K):
            assert index + 1 + max(jt, jf) < len(instructions)
    assert instructions[-2] == (sandbox._RET_K, 0, 0, sandbox._RET_ALLOW)
    assert instructions[-1][3] == instructions[2][3] == sandbox._RET_ERRNO | sandbox._EACCES
    assert (sandbox._JEQ_K, 0, 2, 41) in instructions and (
        sandbox._JEQ_K,
        1,
        0,
        0xC000003E,
    ) in instructions


@pytest.mark.usefixtures("linux")
def test_full_sandbox_with_network_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    libc = use(monkeypatch, FakeLibc(abi=4))
    out = tmp_path / "out.pdf"
    out.touch()
    report = sandbox.apply([tmp_path], [out])
    assert report == SandboxReport(landlock_abi=4, landlock_network=True, seccomp=True)
    assert report.active
    assert struct.unpack("<QQ", libc.attr) == (
        sandbox.write_rights(4),
        sandbox.NET_BIND_TCP | sandbox.NET_CONNECT_TCP,
    )
    assert libc.rules == [sandbox.write_rights(4), sandbox.file_rights(4)]
    assert libc.calls[0] == ("prctl", sandbox._PR_SET_NO_NEW_PRIVS)  # before any restriction
    assert libc.calls[-1] == ("prctl", sandbox._PR_SET_SECCOMP)
    assert report.describe() == (
        "sandbox: landlock abi 4 (files + network), seccomp (no network sockets)"
    )


@pytest.mark.usefixtures("linux")
def test_older_kernel_without_network_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    libc = use(monkeypatch, FakeLibc(abi=3))
    report = sandbox.apply([tmp_path])
    assert report == SandboxReport(landlock_abi=3, seccomp=True)
    assert struct.unpack("<Q", libc.attr) == (sandbox.write_rights(3),)
    assert report.describe() == "sandbox: landlock abi 3 (files), seccomp (no network sockets)"


@pytest.mark.usefixtures("linux")
@pytest.mark.parametrize("fail", ["create", "rule", "restrict"])
def test_landlock_failures_keep_seccomp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: str
) -> None:
    use(monkeypatch, FakeLibc(abi=2, fail=fail))
    assert sandbox.apply([tmp_path]) == SandboxReport(seccomp=True)


@pytest.mark.usefixtures("linux")
def test_no_landlock_and_unknown_architecture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, FakeLibc(abi=-1))
    monkeypatch.setattr(sandbox.platform, "machine", lambda: "riscv64")
    report = sandbox.apply([tmp_path])
    assert report == SandboxReport() and not report.active
    assert report.describe() == "sandbox: not available"


@pytest.mark.usefixtures("linux")
@pytest.mark.parametrize("fail", ["nnp", "seccomp"])
def test_prctl_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: str) -> None:
    use(monkeypatch, FakeLibc(abi=1, fail=fail))
    expected = SandboxReport() if fail == "nnp" else SandboxReport(landlock_abi=1)
    assert sandbox.apply([tmp_path]) == expected


@pytest.mark.usefixtures("linux")
def test_missing_path_or_libc_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeLibc(abi=2))
    assert sandbox.apply([tmp_path / "missing"]) == SandboxReport()

    def no_libc() -> ctypes.CDLL:
        raise OSError("no libc")

    monkeypatch.setattr(sandbox, "_libc", no_libc)
    assert sandbox.apply([tmp_path]) == SandboxReport()


@pytest.mark.parametrize("value", ["off", "OFF", "0", "false", "no"])
def test_can_be_disabled(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(sandbox.DISABLE_ENV, value)
    report = sandbox.apply([Path(".")])
    assert report.disabled and report.describe() == "sandbox: disabled"


def test_other_systems_are_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(sandbox.DISABLE_ENV, raising=False)
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sandbox, "_libc", lambda: pytest.fail("no libc calls"))
    assert sandbox.apply([Path(".")]) == SandboxReport()


def test_worker_confine_grants_temp_output_and_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[tuple[list[Path], list[Path]]] = []

    def fake_apply(dirs: list[Path], files: list[Path]) -> SandboxReport:
        seen.append((dirs, files))
        return SandboxReport(seccomp=True)

    monkeypatch.setattr(sandbox, "apply", fake_apply)
    monkeypatch.setattr(worker.tempfile, "gettempdir", lambda: str(tmp_path / "t"))
    monkeypatch.setattr(worker, "_coverage_data_dirs", lambda: [tmp_path / "cov"])
    out = tmp_path / "out.pdf"
    worker.confine(out)
    assert out.exists()  # created so it can be granted on its own
    assert seen == [([tmp_path / "t", tmp_path / "cov"], [out, Path(os.devnull)])]
    assert "sandbox: seccomp" in capsys.readouterr().err


def test_coverage_data_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delitem(sys.modules, "coverage", raising=False)
    assert worker._coverage_data_dirs() == []

    class Config:
        data_file = str(tmp_path / ".coverage")

    class Current:
        config = Config()

    class Coverage:
        @staticmethod
        def current() -> Current | None:
            return active

    class Module:
        pass

    module = Module()
    module.Coverage = Coverage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "coverage", module)
    active: Current | None = None
    assert worker._coverage_data_dirs() == []
    active = Current()
    assert worker._coverage_data_dirs() == [tmp_path.resolve()]


CHILD = textwrap.dedent("""
    import socket, sys
    from pathlib import Path
    from searchify_pdf.engines import sandbox
    allowed, out, other = map(Path, sys.argv[1:4])
    report = sandbox.apply([allowed], [out, Path("/dev/null")])
    print(report.describe())
    if report.landlock_abi == 0:
        raise SystemExit(0)
    def attempt(name, action):
        try:
            action()
            print(name, "allowed")
        except OSError:
            print(name, "denied")
    attempt("write-allowed", lambda: (allowed / "a").write_text("x"))
    attempt("write-output", lambda: out.write_text("x"))
    attempt("write-other", lambda: (other / "a").write_text("x"))
    attempt("delete-output", out.unlink)
    attempt("read", lambda: Path(sys.executable).read_bytes()[:4])
    attempt("tcp", lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM))
    attempt("udp", lambda: socket.socket(socket.AF_INET6, socket.SOCK_DGRAM))
    attempt("unix", lambda: socket.socket(socket.AF_UNIX).close())
    attempt("devnull", lambda: open("/dev/null", "r+b").close())
    """)


@pytest.mark.skipif(sys.platform != "linux", reason="Landlock and seccomp are Linux features")
def test_real_kernel_restrictions_in_a_child(tmp_path: Path) -> None:
    allowed, other = tmp_path / "allowed", tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    out = tmp_path / "out.pdf"
    out.touch()
    env = {k: v for k, v in os.environ.items() if k != sandbox.DISABLE_ENV}
    if "COVERAGE_PROCESS_START" in env or "COV_CORE_SOURCE" in env:  # pragma: no cover
        env.pop("COVERAGE_PROCESS_START", None)
    done = subprocess.run(
        [sys.executable, "-c", CHILD, str(allowed), str(out), str(other)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=True,
    )
    lines = done.stdout.splitlines()
    if lines[0] == "sandbox: not available" or "landlock" not in lines[0]:
        pytest.skip(f"kernel without Landlock here: {lines[0]}")
    results = dict(line.split(" ", 1) for line in lines[1:])
    assert results == {
        "write-allowed": "allowed",
        "write-output": "allowed",
        "write-other": "denied",
        "delete-output": "denied",
        "read": "allowed",
        "tcp": "denied",
        "udp": "denied" if "seccomp" in lines[0] else results["udp"],
        "unix": "allowed",
        "devnull": "allowed",
    }
    assert not (other / "a").exists()
