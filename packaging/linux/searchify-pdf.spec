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
    excludes=["tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore"],
    noarchive=False,
)
# The GTK3 platform theme plugin needs a full GTK stack; Qt falls back to its own style.
a.binaries = [b for b in a.binaries if "platformthemes/libqgtk3" not in b[0]]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=name,
    debug=False,
    strip=False,
    upx=False,
    console=True,
    runtime_tmpdir=None,
)
