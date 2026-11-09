# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Pure path rules: adjacent output naming and generated-copy recognition.

``Contracts/2025/Acme.pdf`` maps to ``Contracts/2025/Acme_searchable.pdf`` — the copy
always lives beside its original and no output directory is introduced (VISION §3.2).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

PDF_EXTENSION = ".pdf"
STAGING_MARKER = ".searchify-partial"
LOCK_MARKER = ".searchify-lock"


def is_pdf_name(path: Path) -> bool:
    """Case-insensitive ``.pdf`` extension check that ignores our own temp files."""
    name = path.name
    return (
        name.lower().endswith(PDF_EXTENSION)
        and len(name) > len(PDF_EXTENSION)
        and STAGING_MARKER not in name
        and LOCK_MARKER not in name
    )


def output_path_for(source: Path, suffix: str) -> Path:
    """Return the adjacent output path: same directory, stem + suffix, ``.pdf``."""
    return source.with_name(f"{source.stem}{suffix}{PDF_EXTENSION}")


def looks_generated(path: Path, suffixes: Iterable[str]) -> bool:
    """True when the file name ends with any known output suffix (case-insensitive)."""
    stem = path.stem.casefold()
    return any(
        stem.endswith(suffix.casefold()) and stem != suffix.casefold() for suffix in suffixes
    )


def collision_key(path: Path) -> str:
    """Key used to detect destinations that collide on case-insensitive filesystems."""
    return str(path).casefold()


def staging_path_for(destination: Path, token: str) -> Path:
    """Hidden temp file in the destination directory (same filesystem for atomic rename)."""
    return destination.with_name(f".{destination.name}.{token}{STAGING_MARKER}")


def lock_path_for(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}{LOCK_MARKER}")
