# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""The real-life fixture corpus (``tests/fixtures/real/corpus.json``) shared by tests."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

REAL_DIR = Path(__file__).resolve().parent / "fixtures" / "real"


@dataclass(frozen=True)
class RealDocument:
    file: str
    pages: int
    text_layer: bool
    protected: bool
    words: tuple[str, ...]

    @property
    def path(self) -> Path:
        return REAL_DIR / self.file

    @property
    def copy_name(self) -> str:
        return f"{Path(self.file).stem}_searchable.pdf"


def documents() -> list[RealDocument]:
    data = json.loads((REAL_DIR / "corpus.json").read_text(encoding="utf-8"))
    return [
        RealDocument(d["file"], d["pages"], d["text_layer"], d["protected"], tuple(d["words"]))
        for d in data["documents"]
    ]


def copy_corpus(target: Path) -> list[RealDocument]:
    """Copy every corpus file into ``target`` and return the manifest entries."""
    target.mkdir(parents=True, exist_ok=True)
    docs = documents()
    for doc in docs:
        shutil.copy2(doc.path, target / doc.file)
    return docs
