#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Generate the component inventory (SBOM-like JSON) and license texts for a build.

Usage::

    scripts/generate_inventory.py --tessdata DIR --out components.json --licenses-dir DIR

Collects, from the *actual* build environment:

* every installed Python distribution (name, version, license, URL, authors) and its
  license/notice files from ``.dist-info``;
* the Python runtime and Qt version;
* the Tesseract executable and every shared library it links against, resolved to
  Debian packages via ``dpkg -S`` (name, version, copyright file); a Tesseract built
  from source (``/usr/local``, see ``packaging/linux/Dockerfile.build``) is reported from
  its installed ``LICENSE`` and ``VERSION`` files;
* the bundled trained language data with SHA-256 checksums.

Runs on Debian/Ubuntu build hosts; native entries are skipped where ``dpkg`` is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from searchify_pdf import __version__
from searchify_pdf.platform.components import Component, python_components

LICENSE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.IGNORECASE)


def run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout
    except OSError:
        return ""


RUNTIME_ROOTS = ("searchify-pdf", "PySide6-Essentials")


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_closure(roots: tuple[str, ...] = RUNTIME_ROOTS) -> set[str]:
    """Canonical names of the distributions the application needs at run time.

    Walks ``Requires-Dist`` recursively from the roots, skipping extras and requirements
    whose environment markers do not apply, so build/test tools are not reported as
    bundled components.
    """
    from packaging.requirements import Requirement

    seen: set[str] = set()
    stack = [_canonical(r) for r in roots]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        try:
            requires = metadata.requires(name) or []
        except metadata.PackageNotFoundError:
            continue
        seen.add(name)
        for spec in requires:
            req = Requirement(spec)
            if req.marker is not None and not req.marker.evaluate({"extra": ""}):
                continue
            stack.append(_canonical(req.name))
    return seen


def copy_python_licenses(target: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if not name:
            continue
        texts = []
        for file in dist.files or []:
            in_dist_info = ".dist-info" in str(file)
            if in_dist_info and (LICENSE_FILE.search(file.name) or "licenses" in file.parts):
                path = Path(str(dist.locate_file(file)))
                if path.is_file():
                    texts.append(path.read_text(encoding="utf-8", errors="replace"))
        if texts:
            dest = target / f"python-{name.lower()}.txt"
            dest.write_text("\n\n".join(texts), encoding="utf-8")
            found[name.lower()] = dest.name
    return found


SOURCE_BUILD_DOC = Path("/usr/local/share/doc/tesseract")


def source_built_tesseract(target: Path, doc_dir: Path = SOURCE_BUILD_DOC) -> list[Component]:
    """The Tesseract compiled from the pinned upstream release, if this host has one."""
    license_file, version_file = doc_dir / "LICENSE", doc_dir / "VERSION"
    if not license_file.is_file():
        return []
    (target / "native-tesseract-ocr.txt").write_text(
        license_file.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
    )
    version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else ""
    return [
        Component(
            name="tesseract-ocr",
            version=f"{version} (built from source)",
            license="Apache-2.0",
            url="https://github.com/tesseract-ocr/tesseract",
            authors="Tesseract contributors",
            kind="native",
            license_text="licenses/native-tesseract-ocr.txt",
        )
    ]


TRIMMED_ICU_DIR = Path("/opt/icu-data")


def trimmed_icu_data(target: Path, icu_dir: Path = TRIMMED_ICU_DIR) -> list[Component]:
    """The ICU data library rebuilt for the bundled Qt (packaging/linux/build_icu_data.sh)."""
    license_file = icu_dir / "LICENSE"
    if not license_file.is_file():
        return []
    (target / "native-icu-data.txt").write_text(
        license_file.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
    )
    version = (icu_dir / "VERSION").read_text(encoding="utf-8").strip()
    return [
        Component(
            name="ICU data (trimmed to en/de for Qt)",
            version=f"{version} (built from source)",
            license="Unicode-3.0",
            url="https://icu.unicode.org/",
            authors="Unicode, Inc. and others",
            kind="data",
            license_text="licenses/native-icu-data.txt",
        )
    ]


def native_components(target: Path) -> list[Component]:
    tesseract = shutil.which("tesseract")
    if tesseract is None or shutil.which("dpkg") is None:
        return []
    libs = [tesseract]
    for line in run(["ldd", tesseract]).splitlines():
        match = re.search(r"=>\s+(/\S+)", line)
        if match:
            libs.append(match.group(1))
    packages: dict[str, None] = {}
    for lib in libs:
        real = str(Path(lib).resolve())
        owner = run(["dpkg", "-S", real]) or run(["dpkg", "-S", lib])
        if owner:
            packages[owner.split(":")[0].strip()] = None
    result = source_built_tesseract(target) + trimmed_icu_data(target)
    for package in packages:
        version = run(["dpkg-query", "-W", "-f=${Version}", package]).strip()
        homepage = run(["dpkg-query", "-W", "-f=${Homepage}", package]).strip()
        copyright_file = Path("/usr/share/doc") / package / "copyright"
        text = ""
        if copyright_file.is_file():
            text = copyright_file.read_text(encoding="utf-8", errors="replace")
            (target / f"native-{package}.txt").write_text(text, encoding="utf-8")
        licenses = sorted(
            {
                name
                for name in re.findall(r"^License:\s*(\S+)", text, re.MULTILINE)
                if re.fullmatch(r"[A-Za-z0-9.+-]+", name)
            }
        )
        result.append(
            Component(
                name=package,
                version=version,
                license=" AND ".join(licenses) or "see copyright file",
                url=homepage,
                kind="native",
                license_text=f"licenses/native-{package}.txt" if text else "",
            )
        )
    return result


def tessdata_components(tessdata: Path) -> list[Component]:
    entries = []
    for model in sorted(tessdata.glob("*.traineddata")):
        digest = hashlib.sha256(model.read_bytes()).hexdigest()
        entries.append(
            Component(
                name=f"tessdata_fast/{model.name}",
                version=f"4.1.0 sha256:{digest[:16]}",
                license="Apache-2.0",
                url="https://github.com/tesseract-ocr/tessdata_fast",
                authors="Google / Tesseract contributors",
                kind="data",
            )
        )
    return entries


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate the component inventory.")
    parser.add_argument("--tessdata", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--licenses-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.licenses_dir.mkdir(parents=True, exist_ok=True)
    license_files = copy_python_licenses(args.licenses_dir)
    components = [
        Component(
            "Searchify PDF",
            __version__,
            "GPL-3.0-or-later",
            "https://github.com/marcelpetrick/SearchifyMyPDF",
            "Marcel Petrick",
            "application",
            "LICENSE",
        ),
        Component(
            "Python",
            platform.python_version(),
            "PSF-2.0",
            "https://www.python.org/",
            kind="runtime",
        ),
    ]
    try:
        from PySide6 import QtCore

        components.append(
            Component("Qt", QtCore.qVersion(), "LGPL-3.0-only", "https://www.qt.io/", kind="native")
        )
    except ImportError:
        pass
    bundled = runtime_closure()
    components.append(
        Component(
            "PyInstaller bootloader",
            metadata.version("pyinstaller"),
            "GPL-2.0-or-later WITH Bootloader-exception",
            "https://pyinstaller.org/",
            kind="native",
        )
    )
    for component in python_components():
        if _canonical(component.name) not in bundled:
            continue
        text = license_files.get(component.name.lower(), "")
        components.append(
            Component(
                component.name,
                component.version,
                component.license,
                component.url,
                component.authors,
                "python",
                f"licenses/{text}" if text else "",
            )
        )
    components += native_components(args.licenses_dir)
    components += tessdata_components(args.tessdata)
    document = {
        "format": "searchify-pdf-inventory/1",
        "product": "Searchify PDF",
        "version": __version__,
        "components": [c.to_json() for c in components],
    }
    args.out.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"{len(components)} components written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
