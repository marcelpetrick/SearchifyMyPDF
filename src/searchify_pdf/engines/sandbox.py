# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Best-effort sandbox for the OCR worker process on Linux (#13, ADR 0016).

The worker parses untrusted PDFs and images with native code (qpdf, Leptonica,
Tesseract, Ghostscript-free OCRmyPDF pipeline). Before it touches the document it
restricts itself, and everything it starts inherits the restrictions:

* **Landlock** (Linux ≥ 5.13): file-system writes only inside the worker's private
  temporary folder and to the one output file. Reading stays allowed (the interpreter,
  libraries and language data live in many places), so a compromised parser can still
  read files but cannot modify, encrypt or delete them.
* **Landlock network rules** (Linux ≥ 6.7): no TCP connect or bind.
* **seccomp** (x86-64, AArch64): ``socket()`` only for local ``AF_UNIX`` sockets and no
  ``io_uring``, so there is no UDP or raw network either; foreign syscall ABIs (i386,
  x32) are refused.

It is applied with ``no_new_privs`` and cannot be lifted by the worker or its children.
Where the kernel lacks a feature the remaining layers still apply; the report says what
is active. ``SEARCHIFY_PDF_SANDBOX=off`` disables it for troubleshooting.
"""

from __future__ import annotations

import ctypes
import dataclasses
import os
import platform
import struct
from collections.abc import Iterable
from pathlib import Path

DISABLE_ENV = "SEARCHIFY_PDF_SANDBOX"

# --- Landlock (include/uapi/linux/landlock.h); syscall numbers are the same on all arches
_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446
_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1

FS_WRITE_FILE = 1 << 1
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
    seccomp: bool = False
    disabled: bool = False

    @property
    def active(self) -> bool:
        return self.landlock_abi > 0 or self.seccomp

    def describe(self) -> str:
        if self.disabled:
            return "sandbox: disabled"
        parts = []
        if self.landlock_abi:
            net = " + network" if self.landlock_network else ""
            parts.append(f"landlock abi {self.landlock_abi} (files{net})")
        if self.seccomp:
            parts.append("seccomp (no network sockets)")
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


def file_rights(abi: int) -> int:
    """The write rights that can be granted on a single regular file."""
    return FS_WRITE_FILE | (FS_TRUNCATE if abi >= 3 else 0)


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


def _landlock(
    libc: ctypes.CDLL, writable_dirs: list[Path], writable_files: list[Path]
) -> tuple[int, bool]:
    syscall = libc.syscall
    syscall.restype = ctypes.c_long
    abi = int(
        syscall(_SYS_LANDLOCK_CREATE_RULESET, None, ctypes.c_size_t(0), _CREATE_RULESET_VERSION)
    )
    if abi < 1:
        return 0, False
    network = abi >= 4
    attr = (
        struct.pack("<QQ", write_rights(abi), NET_BIND_TCP | NET_CONNECT_TCP)
        if network
        else struct.pack("<Q", write_rights(abi))
    )
    buffer = ctypes.create_string_buffer(attr, len(attr))
    ruleset = int(syscall(_SYS_LANDLOCK_CREATE_RULESET, buffer, ctypes.c_size_t(len(attr)), 0))
    if ruleset < 0:
        return 0, False
    try:
        rules = [(path, write_rights(abi)) for path in writable_dirs]
        rules += [(path, file_rights(abi)) for path in writable_files]
        for path, rights in rules:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = ctypes.create_string_buffer(struct.pack("<Qi", rights, fd), 12)
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


def apply(writable_dirs: Iterable[Path], writable_files: Iterable[Path] = ()) -> SandboxReport:
    """Restrict this process (and its future children). Never raises."""
    if os.environ.get(DISABLE_ENV, "").lower() in {"off", "0", "false", "no"}:
        return SandboxReport(disabled=True)
    if platform.system() != "Linux":
        return SandboxReport()
    dirs = [Path(p) for p in writable_dirs]
    files = [Path(p) for p in writable_files]
    try:
        libc = _libc()
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            return SandboxReport()
        abi, network = _landlock(libc, dirs, files)
        return SandboxReport(landlock_abi=abi, landlock_network=network, seccomp=_seccomp(libc))
    except (OSError, AttributeError, ValueError):
        return SandboxReport()
