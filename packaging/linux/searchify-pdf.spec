# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
# PyInstaller spec: one-file executable with bundled Tesseract and language data.
# Linux: built in a container by build_in_container.sh. Windows/macOS: built natively by
# scripts/build_native_binary.sh. Inputs come from environment variables.
import glob
import os
import shutil
import sys

from PyInstaller.utils.hooks import collect_data_files

name = os.environ["SEARCHIFY_BINARY_NAME"]
tessdata = os.environ["SEARCHIFY_TESSDATA"]
inventory = os.environ["SEARCHIFY_INVENTORY"]
licenses = os.environ["SEARCHIFY_LICENSES"]
tesseract = os.environ.get("SEARCHIFY_TESSERACT") or shutil.which("tesseract")
assert tesseract, "tesseract not found"
ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))  # noqa: F821 - set by PyInstaller

datas = [
    (tessdata, "tessdata"),
    (inventory, "searchify_pdf/resources"),
    (licenses, "licenses"),
    (os.path.join(ROOT, "src/searchify_pdf/resources/searchify-pdf.svg"), "searchify_pdf/resources"),
    (os.path.join(ROOT, "LICENSE"), "."),
]
datas += collect_data_files("ocrmypdf")
datas += collect_data_files("pikepdf")
datas += collect_data_files("pypdfium2_raw")


def _pe_imports(path):
    """DLL names (lower case) a PE file imports, including delay-loaded ones."""
    import pefile

    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories(
        directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
        ]
    )
    entries = getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) + getattr(
        pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []
    )
    names = {entry.dll.decode("ascii", "replace").lower() for entry in entries}
    pe.close()
    return names


def _dll_closure(exe, folder):
    """The DLLs from ``folder`` that ``exe`` needs, directly or transitively."""
    present = {
        os.path.basename(dll).lower(): dll for dll in glob.glob(os.path.join(folder, "*.dll"))
    }
    needed, todo = set(), [exe]
    while todo:
        for name in _pe_imports(todo.pop()):
            if name in present and name not in needed:
                needed.add(name)
                todo.append(present[name])
    return sorted(present[name] for name in needed)


# Windows: tesseract.exe loads its DLLs from its own folder, so exactly the DLLs it imports
# (transitively; not the training tools' cairo/pango/ICU) travel with it into bin/.
# Linux/macOS: PyInstaller resolves the shared-library dependencies itself.
tesseract_binaries = [(tesseract, "bin")]
tesseract_dir = os.path.dirname(os.path.abspath(tesseract))
if sys.platform == "win32":
    tesseract_binaries += [(dll, "bin") for dll in _dll_closure(tesseract, tesseract_dir)]

a = Analysis(
    [os.path.join(ROOT, "packaging/linux/entry.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=tesseract_binaries,
    datas=datas,
    hiddenimports=[
        "searchify_pdf.engines.worker",
        "searchify_pdf.ui.app",
        "ocrmypdf.builtin_plugins",
    ],
    excludes=[
        "tkinter",
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtWebEngineCore",
        # Size (PLAN step 26): optional modules nothing in the application imports.
        "PIL._avif",  # AVIF codec (+ libavif); PDFs never embed AVIF images
        "PIL.AvifImagePlugin",
        "lxml.objectify",
        "lxml.html",
        "setuptools",
        "pkg_resources",
        "_distutils_hack",
    ],
    noarchive=False,
)
# Qt plugins a desktop session never loads. Kept: xcb + wayland (desktops), offscreen
# (headless smoke test), svg/ico/jpeg image formats, input contexts, xcb GL integration.
UNUSED_QT_PLUGINS = (
    "platformthemes/libqgtk3",  # needs a full GTK stack; Qt falls back to its own style
    "platforms/libqeglfs",
    "platforms/libqlinuxfb",
    "platforms/libqminimal",
    "platforms/libqvkkhrdisplay",
    "platforms/libqvnc",
    "egldeviceintegrations/",
    "plugins/generic/",
    "imageformats/libqgif",
    "imageformats/libqicns",
    "imageformats/libqtga",
    "imageformats/libqtiff",
    "imageformats/libqwbmp",
    "imageformats/libqwebp",
)
a.binaries = [b for b in a.binaries if not any(u in b[0] for u in UNUSED_QT_PLUGINS)]
# Same ICU version, data trimmed to the en/de UI (packaging/linux/build_icu_data.sh).
ICU_DATA = "PySide6/Qt/lib/libicudata.so.73"
trimmed_icu = os.environ.get("SEARCHIFY_ICU_DATA", "")
if trimmed_icu:
    a.binaries = [
        (dest, trimmed_icu, kind) if dest == ICU_DATA else (dest, src, kind)
        for dest, src, kind in a.binaries
    ]
    assert any(src == trimmed_icu for _dest, src, _kind in a.binaries), "Qt ICU data not found"
if sys.platform == "win32":
    # Analysis also files bin/'s DLL dependencies at the top level, a second copy nobody
    # loads (35 MB in 0.22.0). Drop a top-level copy from the Tesseract folder unless a
    # binary outside bin/ (a Python extension, Qt) imports it.
    in_bin = {os.path.basename(dest).lower() for dest, _src, _kind in a.binaries
              if dest.lower().startswith("bin\\") or dest.lower().startswith("bin/")}
    used_outside = set()
    for dest, src, kind in a.binaries:
        if kind == "BINARY" and not dest.lower().startswith(("bin\\", "bin/")) and (
            os.path.dirname(os.path.abspath(src)).lower() != tesseract_dir.lower()
        ):
            used_outside |= _pe_imports(src)
    a.binaries = [
        (dest, src, kind)
        for dest, src, kind in a.binaries
        if not (
            os.path.dirname(dest) == ""
            and dest.lower() in in_bin
            and dest.lower() not in used_outside
            and os.path.dirname(os.path.abspath(src)).lower() == tesseract_dir.lower()
        )
    ]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=name,
    debug=False,
    # Drop symbol tables of bundled native libraries (PLAN step 26). Linux only: there is
    # no strip on Windows, and on macOS it would invalidate the (ad-hoc) code signatures.
    strip=sys.platform.startswith("linux"),
    upx=False,
    console=True,
    runtime_tmpdir=None,
)
