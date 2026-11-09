# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Component inventory for the offline About/Licenses view (VISION §13).

Packaged builds ship ``resources/components.json`` generated from the actual build
inputs by ``scripts/generate_inventory.py`` (Python distributions *and* native
components such as Tesseract, Leptonica, Qt and the trained language data). Source
installs fall back to an inventory computed from installed distribution metadata.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable
from importlib import metadata, resources
from typing import Any

INVENTORY_RESOURCE = "resources/components.json"


@dataclasses.dataclass(frozen=True, slots=True)
class Component:
    name: str
    version: str
    license: str
    url: str = ""
    authors: str = ""
    kind: str = "python"
    license_text: str = ""

    def to_json(self) -> dict[str, str]:
        return dataclasses.asdict(self)


def _license_of(meta: Any) -> str:
    expression = meta.get("License-Expression")
    if expression:
        return str(expression)
    classifiers = [
        c.split("::")[-1].strip()
        for c in (meta.get_all("Classifier") or [])
        if c.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(classifiers)
    raw = (meta.get("License") or "").strip()
    return raw.splitlines()[0][:80] if raw else "UNKNOWN"


def _url_of(meta: Any) -> str:
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in {"homepage", "home", "source", "repository", "source code"}:
            return str(url).strip()
    return str(meta.get("Home-page") or "")


def python_components(dists: Iterable[metadata.Distribution] | None = None) -> list[Component]:
    found: dict[str, Component] = {}
    for dist in dists if dists is not None else metadata.distributions():
        meta = dist.metadata
        name = meta.get("Name")
        if not name:
            continue
        authors = meta.get("Author") or meta.get("Author-email") or ""
        found[name.lower()] = Component(
            name=name,
            version=dist.version,
            license=_license_of(meta),
            url=_url_of(meta),
            authors=str(authors),
        )
    return sorted(found.values(), key=lambda c: c.name.lower())


def load_inventory() -> list[Component]:
    """Bundled inventory when present, otherwise installed-distribution metadata."""
    resource = resources.files("searchify_pdf").joinpath(INVENTORY_RESOURCE)
    if resource.is_file():
        data = json.loads(resource.read_text(encoding="utf-8"))
        return [Component(**entry) for entry in data["components"]]
    return python_components()
