# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
# PyInstaller spec: one-file Linux executable with bundled Tesseract and language data.
# Inputs come from environment variables set by build_in_container.sh.
import os
import shutil

from PyInstaller.utils.hooks import collect_data_files

name = os.environ["SEARCHIFY_BINARY_NAME"]
tessdata = os.environ["SEARCHIFY_TESSDATA"]
inventory = os.environ["SEARCHIFY_INVENTORY"]
licenses = os.environ["SEARCHIFY_LICENSES"]
tesseract = shutil.which("tesseract")
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

a = Analysis(
    [os.path.join(ROOT, "packaging/linux/entry.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[(tesseract, "bin")],
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
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=name,
    debug=False,
    strip=True,  # drop symbol tables of bundled native libraries (PLAN step 26)
    upx=False,
    console=True,
    runtime_tmpdir=None,
)
