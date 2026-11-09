# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Snapshot eligible PDFs from files and folders (VISION §3.2).

Rules (documented in ADR 0009):

* Folders are processed recursively; directory symlinks are never traversed and
  symlinked files inside folders are skipped. Both are reported as omissions.
* ``.pdf`` matching is case-insensitive; our hidden staging/lock files are ignored.
* Inside folders, names ending in a known output suffix are excluded: as
  ``generated_copy`` when they carry the Searchify marker, otherwise as
  ``looks_generated`` (a naturally named source; select the file explicitly to process).
* A file given explicitly is processed even if its name looks generated, unless it
  carries the marker (then it is reported as ``generated_copy``).
* Inputs are deduplicated by real path; destinations colliding case-insensitively with
  each other or with another source are reported as ``destination_collision``.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from searchify_pdf.domain.jobs import Omission, Reason
from searchify_pdf.domain.paths import collision_key, is_pdf_name, looks_generated, output_path_for


@dataclasses.dataclass(frozen=True, slots=True)
class Candidate:
    source: Path
    destination: Path
    explicit: bool
    looks_generated: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class DiscoveryResult:
    candidates: tuple[Candidate, ...]
    omissions: tuple[Omission, ...]


def _walk(folder: Path, omissions: list[Omission]) -> Iterable[Path]:
    def on_error(error: OSError) -> None:
        omissions.append(Omission(Path(error.filename or folder), Reason.UNREADABLE, str(error)))

    for root, dirs, files in os.walk(folder, onerror=on_error, followlinks=False):
        root_path = Path(root)
        for name in sorted(dirs):
            if (root_path / name).is_symlink():
                omissions.append(Omission(root_path / name, Reason.SYMLINK))
        dirs.sort()
        for name in sorted(files):
            path = root_path / name
            if not is_pdf_name(path):
                continue
            if path.is_symlink():
                omissions.append(Omission(path, Reason.SYMLINK))
                continue
            yield path


def discover(
    inputs: Sequence[Path],
    suffix: str,
    known_suffixes: Sequence[str],
    has_marker: Callable[[Path], bool],
) -> DiscoveryResult:
    omissions: list[Omission] = []
    found: list[tuple[Path, bool]] = []
    for raw in inputs:
        path = Path(os.path.abspath(raw))  # noqa: PTH100 - keep symlink names, unlike resolve()
        if path.is_dir():
            found.extend((p, False) for p in _walk(path, omissions))
        elif path.is_file():
            if is_pdf_name(path):
                found.append((path, True))
            else:
                omissions.append(Omission(path, Reason.NOT_PDF))
        else:
            omissions.append(Omission(path, Reason.NOT_FOUND))

    candidates: list[Candidate] = []
    seen_real: set[str] = set()
    for path, explicit in found:
        real = os.path.realpath(path)
        if real in seen_real:
            continue
        seen_real.add(real)
        generated_name = looks_generated(path, known_suffixes)
        if generated_name:
            if has_marker(path):
                omissions.append(Omission(path, Reason.GENERATED_COPY))
                continue
            if not explicit:
                omissions.append(Omission(path, Reason.LOOKS_GENERATED))
                continue
        candidates.append(Candidate(path, output_path_for(path, suffix), explicit, generated_name))

    source_keys = {collision_key(c.source) for c in candidates}
    dest_keys: set[str] = set()
    accepted: list[Candidate] = []
    for candidate in sorted(candidates, key=lambda c: str(c.source)):
        key = collision_key(candidate.destination)
        if key in dest_keys or key in source_keys:
            omissions.append(
                Omission(candidate.source, Reason.DESTINATION_COLLISION, str(candidate.destination))
            )
            continue
        dest_keys.add(key)
        accepted.append(candidate)
    return DiscoveryResult(tuple(accepted), tuple(omissions))
