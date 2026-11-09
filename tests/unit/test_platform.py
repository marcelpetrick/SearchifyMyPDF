# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
import os
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from searchify_pdf.platform import components, desktop
from searchify_pdf.platform.components import Component, load_inventory, python_components
from searchify_pdf.platform.desktop import (
    default_data_home,
    install_desktop_entry,
    launch_command,
    open_folder,
)
from searchify_pdf.platform.runtime import configure_bundled_runtime, external_env


def test_configure_bundled_runtime(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin"}
    assert not configure_bundled_runtime(env, None)
    assert not configure_bundled_runtime(env, tmp_path)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "tesseract").write_text("")
    assert configure_bundled_runtime(env, tmp_path)
    assert env["PATH"].split(os.pathsep) == [str(tmp_path / "bin"), "/usr/bin"]
    assert "TESSDATA_PREFIX" not in env
    (tmp_path / "tessdata").mkdir()
    env2: dict[str, str] = {}
    assert configure_bundled_runtime(env2, tmp_path)
    assert env2 == {"PATH": str(tmp_path / "bin"), "TESSDATA_PREFIX": str(tmp_path / "tessdata")}


def test_external_env_restores_library_path() -> None:
    assert (
        external_env({"LD_LIBRARY_PATH": "/b", "LD_LIBRARY_PATH_ORIG": "/a"})["LD_LIBRARY_PATH"]
        == "/a"
    )
    assert "LD_LIBRARY_PATH" not in external_env(
        {"LD_LIBRARY_PATH": "/b", "_PYI_APPLICATION_HOME_DIR": "/x"}
    )
    assert external_env({"LD_LIBRARY_PATH": "/b"}) == {"LD_LIBRARY_PATH": "/b"}


def test_launch_command() -> None:
    assert launch_command(frozen=False, executable="/py", appimage="/a.AppImage") == ["/a.AppImage"]
    assert launch_command(frozen=True, executable="/opt/searchify-pdf", appimage=None) == [
        "/opt/searchify-pdf"
    ]
    assert launch_command(frozen=False, executable="/py", appimage=None) == [
        "/py",
        "-m",
        "searchify_pdf",
    ]


def test_install_desktop_entry(tmp_path: Path) -> None:
    entry = install_desktop_entry(tmp_path, ["/opt/my apps/searchify-pdf"])
    text = entry.read_text()
    assert "Exec='/opt/my apps/searchify-pdf' %F" in text
    assert "MimeType=application/pdf;inode/directory;" in text
    icon = tmp_path / "icons" / "hicolor" / "scalable" / "apps" / "searchify-pdf.svg"
    assert icon.read_bytes().startswith(b"<svg")
    assert f"Icon={icon}" in text
    assert install_desktop_entry(tmp_path, ["/x"]) == entry  # idempotent


def test_default_data_home() -> None:
    assert default_data_home({"XDG_DATA_HOME": "/d"}) == Path("/d")
    assert default_data_home({}) == Path.home() / ".local" / "share"


@pytest.mark.parametrize(
    ("platform", "program"),
    [("linux", "xdg-open"), ("darwin", "open"), ("win32", "explorer")],
)
def test_open_folder(platform: str, program: str) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    open_folder(Path("/tmp/x"), platform=platform, popen=lambda cmd, **kw: calls.append((cmd, kw)))
    assert calls[0][0] == [program, "/tmp/x"]
    assert calls[0][1]["start_new_session"] is True


class _Dist:
    def __init__(self, fields: list[tuple[str, str]], version: str = "1.0") -> None:
        self.metadata = Message()
        for key, value in fields:
            self.metadata[key] = value
        self.version = version


def test_python_components_metadata_variants() -> None:
    dists = [
        _Dist(
            [
                ("Name", "Alpha"),
                ("License-Expression", "MIT"),
                ("Project-URL", "Homepage, https://a"),
            ]
        ),
        _Dist(
            [
                ("Name", "beta"),
                ("Classifier", "License :: OSI Approved :: BSD License"),
                ("Home-page", "https://b"),
            ]
        ),
        _Dist([("Name", "Gamma"), ("License", "Apache 2.0\nlong text"), ("Author", "G")]),
        _Dist([("Name", "delta"), ("Project-URL", "Docs, https://d")]),
        _Dist([]),
    ]
    found = {c.name: c for c in python_components(dists)}  # type: ignore[arg-type]
    assert found["Alpha"].license == "MIT" and found["Alpha"].url == "https://a"
    assert found["beta"].license == "BSD License" and found["beta"].url == "https://b"
    assert found["Gamma"].license == "Apache 2.0" and found["Gamma"].authors == "G"
    assert found["delta"].license == "UNKNOWN" and found["delta"].url == ""
    assert len(found) == 4


def test_load_inventory_runtime_and_bundled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = {c.name.lower() for c in load_inventory()}
    assert {"ocrmypdf", "pikepdf"} <= runtime
    bundled = tmp_path / "components.json"
    bundled.write_text(
        '{"components": [{"name": "Tesseract", "version": "5", "license": "Apache-2.0", "kind": "native"}]}'
    )

    class _Files:
        def joinpath(self, _: str) -> Path:
            return bundled

    monkeypatch.setattr(components.resources, "files", lambda _pkg: _Files())
    assert load_inventory() == [Component("Tesseract", "5", "Apache-2.0", kind="native")]
    assert load_inventory()[0].to_json()["kind"] == "native"


def test_icon_resource() -> None:
    assert b"svg" in desktop.icon_bytes()
