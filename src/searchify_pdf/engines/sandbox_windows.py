# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Windows layer of the parser sandbox (#13, ADR 0016): Low integrity.

The process lowers its own token to the Low mandatory integrity level, which it can't
raise again; every child (Tesseract) inherits it. Windows then refuses any write to an
object labelled Medium or higher, which is everything the user owns (documents, the
desktop, the profile, the registry). Before lowering, the writable folders and files
get a Low label, the folders inheritably, so the work files and the output stay
writable.

Low integrity doesn't restrict reading or networking; AppContainer would, but it needs
every runtime file granted by ACL and isn't available to an unpackaged program in a
reliable way. If any label can't be set, the token isn't lowered, so a conversion never
fails because of the sandbox.
"""

from __future__ import annotations

import ctypes
from collections.abc import Iterable
from pathlib import Path
from typing import Any

LOW_INTEGRITY_SID = "S-1-16-4096"
INHERITED_LOW_LABEL = "S:(ML;OICI;NW;;;LW)"  # no write-up, inherited by files and folders
LOW_LABEL = "S:(ML;;NW;;;LW)"
_SDDL_REVISION_1 = 1
_SE_FILE_OBJECT = 1
_LABEL_SECURITY_INFORMATION = 0x10
_TOKEN_QUERY = 0x0008
_TOKEN_ADJUST_DEFAULT = 0x0080
_TOKEN_INTEGRITY_LEVEL = 25
_SE_GROUP_INTEGRITY = 0x20


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", ctypes.c_uint32)]


def _dlls() -> tuple[Any, Any]:  # pragma: no cover - Windows only
    windll = getattr(ctypes, "WinDLL")  # noqa: B009 - absent from ctypes off Windows
    return windll("advapi32", use_last_error=True), windll("kernel32", use_last_error=True)


def _label(advapi: Any, kernel: Any, path: Path, sddl: str) -> bool:  # pragma: no cover
    descriptor = ctypes.c_void_p()
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
    if not convert(sddl, _SDDL_REVISION_1, ctypes.byref(descriptor), None):
        return False
    try:
        present, defaulted, sacl = ctypes.c_int(), ctypes.c_int(), ctypes.c_void_p()
        get_sacl = advapi.GetSecurityDescriptorSacl
        get_sacl.argtypes = [ctypes.c_void_p] * 4
        if not get_sacl(
            descriptor, ctypes.byref(present), ctypes.byref(sacl), ctypes.byref(defaulted)
        ):
            return False
        set_info = advapi.SetNamedSecurityInfoW
        set_info.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        set_info.restype = ctypes.c_uint32
        result = set_info(
            str(path), _SE_FILE_OBJECT, _LABEL_SECURITY_INFORMATION, None, None, None, sacl
        )
        return bool(result == 0)
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(descriptor)


def _lower(advapi: Any, kernel: Any) -> bool:  # pragma: no cover - Windows only
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    advapi.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    token = ctypes.c_void_p()
    access = _TOKEN_QUERY | _TOKEN_ADJUST_DEFAULT
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), access, ctypes.byref(token)):
        return False
    sid = ctypes.c_void_p()
    try:
        advapi.ConvertStringSidToSidW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
        if not advapi.ConvertStringSidToSidW(LOW_INTEGRITY_SID, ctypes.byref(sid)):
            return False
        advapi.GetLengthSid.argtypes = [ctypes.c_void_p]
        label = _SidAndAttributes(sid, _SE_GROUP_INTEGRITY)
        size = ctypes.sizeof(label) + advapi.GetLengthSid(sid)
        advapi.SetTokenInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        return bool(
            advapi.SetTokenInformation(token, _TOKEN_INTEGRITY_LEVEL, ctypes.byref(label), size)
        )
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        if sid.value:
            kernel.LocalFree(sid)
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(token)


def apply(
    writable_dirs: Iterable[Path], writable_files: Iterable[Path]
) -> bool:  # pragma: no cover - exercised on the Windows runner only
    """Label the writable paths Low, then drop this process to Low integrity."""
    advapi, kernel = _dlls()
    labels = [(Path(p), INHERITED_LOW_LABEL) for p in writable_dirs]
    labels += [(Path(p), LOW_LABEL) for p in writable_files]
    for path, sddl in labels:
        if not _label(advapi, kernel, path, sddl):
            return False
    return _lower(advapi, kernel)
