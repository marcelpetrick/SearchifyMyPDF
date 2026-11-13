# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Best-effort sandbox for the OCR worker process on Linux (#13, ADR 0016).

The worker parses untrusted PDFs and images with native code (qpdf, Leptonica,
Tesseract, Ghostscript-free OCRmyPDF pipeline). Before it touches the document it
restricts itself, and everything it starts inherits the restrictions:

* **Landlock** (Linux ≥ 5.13): file-system writes only inside the worker's private
  temporary folder and to the one output file. Reading is limited to the runtime (the
  system folders, the Python installation, Tesseract and its language data, see
  :func:`runtime_read_dirs`) and the files the caller names, so a compromised parser can
  neither modify nor read the user's other documents.
* **Landlock network rules** (Linux ≥ 6.7): no TCP connect or bind.
* **seccomp** (x86-64, AArch64): ``socket()`` only for local ``AF_UNIX`` sockets and no
  ``io_uring``, so there is no UDP or raw network either; foreign syscall ABIs (i386,
  x32) are refused.

It is applied with ``no_new_privs`` and cannot be lifted by the worker or its children.
Where the kernel lacks a feature the remaining layers still apply; the report says what
is active. ``SEARCHIFY_PDF_SANDBOX=off`` disables it for troubleshooting, and
``SEARCHIFY_PDF_SANDBOX=allow-reads`` keeps everything except the read restriction (for
installations that keep runtime files somewhere unusual).
"""

from __future__ import annotations

import ctypes
import dataclasses
import os
import platform
import struct
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

DISABLE_ENV = "SEARCHIFY_PDF_SANDBOX"
ALLOW_READS = "allow-reads"
# Folders the runtime may load from; user data lives elsewhere (/home, /media, /mnt, /tmp…)
SYSTEM_READ_DIRS = (
    "/usr",
    "/lib",
    "/lib32",
    "/lib64",
    "/bin",
    "/sbin",
    "/etc",
    "/opt",
    "/nix",
    "/gnu",
    "/snap",
    "/proc",
    "/sys",
    "/dev",
)

# --- Landlock (include/uapi/linux/landlock.h); syscall numbers are the same on all arches
_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446
_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1

FS_EXECUTE = 1 << 0
FS_WRITE_FILE = 1 << 1
FS_READ_FILE = 1 << 2
FS_READ_DIR = 1 << 3
FS_REMOVE_DIR = 1 << 4
FS_REMOVE_FILE = 1 << 5
FS_MAKE_CHAR = 1 << 6
FS_MAKE_DIR = 1 << 7
FS_MAKE_REG = 1 << 8
FS_MAKE_SOCK = 1 << 9
FS_MAKE_FIFO = 1 << 10
FS_MAKE_BLOCK = 1 << 11
FS_MAKE_SYM = 1 << 12
FS_REFER = 1 << 13  # ABI 2
FS_TRUNCATE = 1 << 14  # ABI 3
NET_BIND_TCP = 1 << 0  # ABI 4
NET_CONNECT_TCP = 1 << 1  # ABI 4
READ_RIGHTS = FS_EXECUTE | FS_READ_FILE | FS_READ_DIR

# --- seccomp (include/uapi/linux/seccomp.h, filter.h, audit.h)
_PR_SET_NO_NEW_PRIVS = 38
_PR_SET_SECCOMP = 22
_SECCOMP_MODE_FILTER = 2
_RET_ALLOW = 0x7FFF0000
_RET_ERRNO = 0x00050000
_EACCES = 13
_AF_UNIX = 1
_X32_SYSCALL_BIT = 0x40000000
_SYS_IO_URING_SETUP = 425  # same number on x86-64 and AArch64
_LD_W_ABS = 0x20
_JEQ_K = 0x15
_JGE_K = 0x35
_RET_K = 0x06
# machine → (AUDIT_ARCH_*, socket syscall number)
_ARCHES = {
    "x86_64": (0xC000003E, 41),
    "amd64": (0xC000003E, 41),
    "aarch64": (0xC00000B7, 198),
    "arm64": (0xC00000B7, 198),
}


@dataclasses.dataclass(frozen=True, slots=True)
class SandboxReport:
    landlock_abi: int = 0  # 0: no file-system restriction
    landlock_network: bool = False
    landlock_reads: bool = False
    seatbelt: bool = False  # macOS
    seatbelt_reads: bool = False
    low_integrity: bool = False  # Windows
    seccomp: bool = False
    disabled: bool = False

    @property
    def active(self) -> bool:
        return self.landlock_abi > 0 or self.seccomp or self.seatbelt or self.low_integrity

    def describe(self) -> str:
        if self.disabled:
            return "sandbox: disabled"
        parts = []
        if self.landlock_abi:
            scope = ["writes"]
            if self.landlock_reads:
                scope.append("reads")
            if self.landlock_network:
                scope.append("network")
            parts.append(f"landlock abi {self.landlock_abi} ({', '.join(scope)})")
        if self.seccomp:
            parts.append("seccomp (no network sockets)")
        if self.seatbelt:
            reads = ", reads" if self.seatbelt_reads else ""
            parts.append(f"seatbelt (writes{reads}, network)")
        if self.low_integrity:
            parts.append("low integrity (writes)")
        return "sandbox: " + (", ".join(parts) if parts else "not available")


def write_rights(abi: int) -> int:
    """Every right that modifies the file system, as far as ``abi`` knows it."""
    rights = (
        FS_WRITE_FILE
        | FS_REMOVE_DIR
        | FS_REMOVE_FILE
        | FS_MAKE_CHAR
        | FS_MAKE_DIR
        | FS_MAKE_REG
        | FS_MAKE_SOCK
        | FS_MAKE_FIFO
        | FS_MAKE_BLOCK
        | FS_MAKE_SYM
    )
    if abi >= 2:
        rights |= FS_REFER
    if abi >= 3:
        rights |= FS_TRUNCATE
    return rights


def _instruction(code: int, jt: int, jf: int, k: int) -> bytes:
    return struct.pack("<HBBI", code, jt, jf, k)


def seccomp_program(audit_arch: int, socket_nr: int) -> bytes:
    """Classic BPF: refuse foreign ABIs, io_uring and non-AF_UNIX sockets; allow the rest."""
    errno = _RET_ERRNO | _EACCES
    return b"".join(
        [
            _instruction(_LD_W_ABS, 0, 0, 4),  # 0: arch
            _instruction(_JEQ_K, 1, 0, audit_arch),  # 1: ours → 3
            _instruction(_RET_K, 0, 0, errno),  # 2: foreign ABI (e.g. int 0x80)
            _instruction(_LD_W_ABS, 0, 0, 0),  # 3: syscall number
            _instruction(_JGE_K, 5, 0, _X32_SYSCALL_BIT),  # 4: x32 → 10
            _instruction(_JEQ_K, 4, 0, _SYS_IO_URING_SETUP),  # 5: io_uring → 10
            _instruction(_JEQ_K, 0, 2, socket_nr),  # 6: socket → 7, else → 9
            _instruction(_LD_W_ABS, 0, 0, 16),  # 7: args[0] (low word) = domain
            _instruction(_JEQ_K, 0, 1, _AF_UNIX),  # 8: AF_UNIX → 9, else → 10
            _instruction(_RET_K, 0, 0, _RET_ALLOW),  # 9
            _instruction(_RET_K, 0, 0, errno),  # 10
        ]
    )


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def _landlock(libc: ctypes.CDLL, rules: list[tuple[Path, int]], handled: int) -> tuple[int, bool]:
    syscall = libc.syscall
    syscall.restype = ctypes.c_long
    abi = int(
        syscall(_SYS_LANDLOCK_CREATE_RULESET, None, ctypes.c_size_t(0), _CREATE_RULESET_VERSION)
    )
    if abi < 1:
        return 0, False
    network = abi >= 4
    handled_fs = handled & (write_rights(abi) | READ_RIGHTS)
    attr = (
        struct.pack("<QQ", handled_fs, NET_BIND_TCP | NET_CONNECT_TCP)
        if network
        else struct.pack("<Q", handled_fs)
    )
    buffer = ctypes.create_string_buffer(attr, len(attr))
    ruleset = int(syscall(_SYS_LANDLOCK_CREATE_RULESET, buffer, ctypes.c_size_t(len(attr)), 0))
    if ruleset < 0:
        return 0, False
    try:
        for path, rights in rules:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = ctypes.create_string_buffer(struct.pack("<Qi", rights & handled_fs, fd), 12)
                if syscall(_SYS_LANDLOCK_ADD_RULE, ruleset, _RULE_PATH_BENEATH, rule, 0) != 0:
                    return 0, False
            finally:
                os.close(fd)
        if syscall(_SYS_LANDLOCK_RESTRICT_SELF, ruleset, 0) != 0:
            return 0, False
    finally:
        os.close(ruleset)
    return abi, network


def _seccomp(libc: ctypes.CDLL) -> bool:
    arch = _ARCHES.get(platform.machine().lower())
    if arch is None:
        return False
    program = seccomp_program(*arch)
    buffer = ctypes.create_string_buffer(program, len(program))
    fprog = _SockFprog(len(program) // 8, ctypes.addressof(buffer))
    prctl = libc.prctl
    prctl.restype = ctypes.c_int
    result = prctl(_PR_SET_SECCOMP, _SECCOMP_MODE_FILTER, ctypes.byref(fprog), 0, 0)
    return bool(result == 0)


def _contains(outer: Path, inner: Path) -> bool:
    return inner == outer or outer in inner.parents


def runtime_read_dirs(env: Mapping[str, str] | None = None, home: Path | None = None) -> list[Path]:
    """Folders a sandboxed Python + Tesseract process needs to read, without user data.

    The system folders, the Python installation and import path, ``PATH`` entries (and
    their prefix outside the home folder), the bundle's library path and the language
    data. Nothing that is the home folder or contains it is ever included, so neither
    the working directory nor ``~/.local/bin``'s parent opens the user's documents.
    """
    env = os.environ if env is None else env
    home = (home or Path.home()).resolve()
    candidates = [Path(p) for p in SYSTEM_READ_DIRS]
    candidates += [Path(sys.prefix), Path(sys.base_prefix), Path(sys.exec_prefix)]
    candidates += [Path(sys.executable).resolve().parent.parent]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle))
    cwd = Path.cwd().resolve()
    candidates += [Path(p) for p in sys.path if p and Path(p).resolve() != cwd]
    for name in ("PATH", "LD_LIBRARY_PATH"):
        for entry in env.get(name, "").split(os.pathsep):
            if entry and Path(entry).is_absolute():
                resolved = Path(entry).resolve()
                candidates.append(resolved)
                if not _contains(home, resolved.parent):  # /opt/x/bin → /opt/x, never ~/.local
                    candidates.append(resolved.parent)
    tessdata = env.get("TESSDATA_PREFIX")
    if tessdata:
        candidates.append(Path(tessdata))
    found: list[Path] = []
    for candidate in candidates:
        path = candidate.resolve() if candidate.is_absolute() else None
        if path is None or not path.is_dir() or _contains(path, home) or path in found:
            continue
        found.append(path)
    # nested folders add nothing once their parent is granted
    return [p for p in found if not any(o != p and _contains(o, p) for o in found)]


def _apply_darwin(
    writable_dirs: Iterable[Path],
    writable_files: Iterable[Path],
    readable_dirs: Iterable[Path] | None,
    readable_files: Iterable[Path],
    restrict_reads: bool,
) -> SandboxReport:
    from searchify_pdf.engines import sandbox_darwin

    readable = [p for p in readable_dirs or () if Path(p).is_dir()] if restrict_reads else None
    files = [p for p in (Path(sys.executable), *map(Path, readable_files)) if p.is_file()]
    text = sandbox_darwin.profile(writable_dirs, writable_files, readable, files)
    try:
        applied = _seatbelt(text)
    except (OSError, AttributeError, ValueError):
        applied = False
    return SandboxReport(seatbelt=applied, seatbelt_reads=applied and restrict_reads)


def _seatbelt(text: str) -> bool:  # pragma: no cover - macOS only
    from searchify_pdf.engines import sandbox_darwin

    return sandbox_darwin.apply(text)


def _apply_windows(writable_dirs: Iterable[Path], writable_files: Iterable[Path]) -> SandboxReport:
    # NUL can't carry a label and needs none: devices aren't integrity-checked for writes
    files = [Path(p) for p in writable_files if str(p).lower() not in {"nul", os.devnull}]
    try:
        lowered = _low_integrity(list(writable_dirs), files)
    except (OSError, AttributeError, ValueError):
        lowered = False
    return SandboxReport(low_integrity=lowered)


def _low_integrity(dirs: list[Path], files: list[Path]) -> bool:  # pragma: no cover - Windows
    from searchify_pdf.engines import sandbox_windows

    return sandbox_windows.apply(dirs, files)


def apply(
    writable_dirs: Iterable[Path],
    writable_files: Iterable[Path] = (),
    *,
    readable_dirs: Iterable[Path] | None = None,
    readable_files: Iterable[Path] = (),
) -> SandboxReport:
    """Restrict this process (and its future children). Never raises.

    ``readable_dirs=None`` leaves reading unrestricted; otherwise only those folders,
    ``readable_files``, the writable paths and the running executable can be read (paths
    that don't exist are skipped). The executable is granted on its own, never its
    folder: a one-file build loads its modules from itself and may sit in Downloads.
    """
    setting = os.environ.get(DISABLE_ENV, "").lower()
    if setting in {"off", "0", "false", "no"}:
        return SandboxReport(disabled=True)
    restrict_reads = readable_dirs is not None and setting != ALLOW_READS
    system = platform.system()
    if system == "Darwin":
        return _apply_darwin(
            writable_dirs, writable_files, readable_dirs, readable_files, restrict_reads
        )
    if system == "Windows":
        return _apply_windows(writable_dirs, writable_files)
    if system != "Linux":
        return SandboxReport()
    handled = ~0 if restrict_reads else ~READ_RIGHTS
    rules = [(Path(p), ~0) for p in writable_dirs]
    rules += [(Path(p), FS_WRITE_FILE | FS_TRUNCATE | FS_READ_FILE) for p in writable_files]
    if restrict_reads:
        rules += [(Path(p), READ_RIGHTS) for p in readable_dirs or () if Path(p).is_dir()]
        files = [Path(sys.executable), *(Path(p) for p in readable_files)]
        rules += [(p, FS_READ_FILE | FS_EXECUTE) for p in files if p.is_file()]
    try:
        libc = _libc()
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            return SandboxReport()
        abi, network = _landlock(libc, rules, handled)
        return SandboxReport(
            landlock_abi=abi,
            landlock_network=network,
            landlock_reads=bool(abi) and restrict_reads,
            seccomp=_seccomp(libc),
        )
    except (OSError, AttributeError, ValueError):
        return SandboxReport()
