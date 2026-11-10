# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Validated, immutable application settings and their JSON representation.

The settings object is a frozen dataclass so every job can take an immutable
snapshot (VISION §3.4). Parsing is strict: unknown enum values, out-of-range
numbers and malformed suffixes raise :class:`SettingsError` with a reason code.
Settings are data only; nothing in the file is ever executed.
"""

from __future__ import annotations

import dataclasses
import enum
import re
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = 2
MAX_FIXED_WORKERS = 64
MIN_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 24 * 3600
SUFFIX_PATTERN = re.compile(r"^[A-Za-z0-9_\-.]{1,40}$")
LANGUAGE_PATTERN = re.compile(r"^[a-z]{3}(_[a-z]+)?$")


class ExistingTextPolicy(enum.StrEnum):
    """What to do when a source PDF already contains recognized/digital text."""

    ALWAYS_REPLACE = "always_replace"
    ASK = "ask"
    NEVER_REPLACE = "never_replace"


class ExistingOutputPolicy(enum.StrEnum):
    """What to do when the searchable copy already exists beside the original."""

    OVERWRITE = "overwrite"
    ASK = "ask"
    NEVER_OVERWRITE = "never_overwrite"


class WorkerMode(enum.StrEnum):
    AUTO = "auto"
    SEQUENTIAL = "sequential"
    FIXED = "fixed"


class Theme(enum.StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class UiLanguage(enum.StrEnum):
    ENGLISH = "en"
    GERMAN = "de"


class SettingsError(ValueError):
    """Raised for invalid settings; ``code`` is a stable, translatable reason code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclasses.dataclass(frozen=True, slots=True)
class Settings:
    """All user-configurable behavior. Defaults follow VISION §2/§4/§5."""

    ocr_languages: tuple[str, ...] = ("eng", "deu")
    deskew: bool = False
    rotate_pages: bool = False
    existing_text_policy: ExistingTextPolicy = ExistingTextPolicy.NEVER_REPLACE
    existing_output_policy: ExistingOutputPolicy = ExistingOutputPolicy.ASK
    output_suffix: str = "_searchable"
    previous_suffixes: tuple[str, ...] = ()
    worker_mode: WorkerMode = WorkerMode.AUTO
    fixed_workers: int = 2
    statistics_enabled: bool = False
    theme: Theme = Theme.SYSTEM
    ui_language: UiLanguage = UiLanguage.ENGLISH
    timeout_seconds: int = 1800
    # Owner-restricted PDFs (open without a password, but forbid e.g. copying text) are
    # rejected unless enabled; the copy keeps the same restrictions (ADR 0011).
    process_restricted_pdfs: bool = False
    # "Ask me" for existing text: first compare up to three pages with a fresh
    # recognition and show how well they agree (#6, domain/text_quality.py).
    cross_check_existing_text: bool = True

    def __post_init__(self) -> None:
        validate(self)

    def with_changes(self, **changes: Any) -> Settings:
        """Return a validated copy with ``changes`` applied.

        Changing the output suffix remembers the old one in ``previous_suffixes`` so
        earlier generated copies are still recognized and never re-processed.
        """
        new_suffix = changes.get("output_suffix")
        if new_suffix is not None and new_suffix != self.output_suffix:
            history = [s for s in (self.output_suffix, *self.previous_suffixes) if s != new_suffix]
            changes.setdefault("previous_suffixes", tuple(dict.fromkeys(history))[:10])
        return dataclasses.replace(self, **changes)

    @property
    def known_suffixes(self) -> tuple[str, ...]:
        return (self.output_suffix, *self.previous_suffixes)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "ocr_languages": list(self.ocr_languages),
            "deskew": self.deskew,
            "rotate_pages": self.rotate_pages,
            "existing_text_policy": self.existing_text_policy.value,
            "existing_output_policy": self.existing_output_policy.value,
            "output_suffix": self.output_suffix,
            "previous_suffixes": list(self.previous_suffixes),
            "worker_mode": self.worker_mode.value,
            "fixed_workers": self.fixed_workers,
            "statistics_enabled": self.statistics_enabled,
            "theme": self.theme.value,
            "ui_language": self.ui_language.value,
            "timeout_seconds": self.timeout_seconds,
            "process_restricted_pdfs": self.process_restricted_pdfs,
            "cross_check_existing_text": self.cross_check_existing_text,
        }


def validate(settings: Settings) -> None:
    """Raise :class:`SettingsError` if ``settings`` violates a documented bound."""
    if not settings.ocr_languages:
        raise SettingsError("languages_empty")
    for lang in settings.ocr_languages:
        if not isinstance(lang, str) or not LANGUAGE_PATTERN.fullmatch(lang):
            raise SettingsError("language_invalid", repr(lang))
    if len(set(settings.ocr_languages)) != len(settings.ocr_languages):
        raise SettingsError("language_duplicate")
    for suffix in settings.known_suffixes:
        if not isinstance(suffix, str) or not SUFFIX_PATTERN.fullmatch(suffix):
            raise SettingsError("suffix_invalid", repr(suffix))
        if suffix.strip(".") == "" or suffix.lower().endswith(".pdf"):
            raise SettingsError("suffix_invalid", repr(suffix))
    _check_enum(settings.existing_text_policy, ExistingTextPolicy)
    _check_enum(settings.existing_output_policy, ExistingOutputPolicy)
    _check_enum(settings.worker_mode, WorkerMode)
    _check_enum(settings.theme, Theme)
    _check_enum(settings.ui_language, UiLanguage)
    for flag in (
        settings.deskew,
        settings.rotate_pages,
        settings.statistics_enabled,
        settings.process_restricted_pdfs,
        settings.cross_check_existing_text,
    ):
        if not isinstance(flag, bool):
            raise SettingsError("flag_invalid", repr(flag))
    if (
        isinstance(settings.fixed_workers, bool)
        or not isinstance(settings.fixed_workers, int)
        or not 1 <= settings.fixed_workers <= MAX_FIXED_WORKERS
    ):
        raise SettingsError("workers_out_of_range", repr(settings.fixed_workers))
    if (
        isinstance(settings.timeout_seconds, bool)
        or not isinstance(settings.timeout_seconds, int)
        or not MIN_TIMEOUT_SECONDS <= settings.timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise SettingsError("timeout_out_of_range", repr(settings.timeout_seconds))


def _check_enum(value: object, enum_type: type[enum.Enum]) -> None:
    if not isinstance(value, enum_type):
        raise SettingsError("choice_invalid", repr(value))


def migrate(data: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade an older settings document to :data:`SCHEMA_VERSION`.

    * v1 stored ``languages`` as a ``"eng+deu"`` string and had no previous suffixes.
    """
    version = data.get("schema_version", 1)
    if isinstance(version, bool) or not isinstance(version, int):
        raise SettingsError("schema_invalid", repr(version))
    if version > SCHEMA_VERSION:
        raise SettingsError("schema_too_new", str(version))
    result = dict(data)
    if version < 2:
        languages = result.pop("languages", None)
        if isinstance(languages, str):
            result["ocr_languages"] = [part for part in languages.split("+") if part]
        result.setdefault("previous_suffixes", [])
    result["schema_version"] = SCHEMA_VERSION
    return result


_ENUM_FIELDS: dict[str, type[enum.Enum]] = {
    "existing_text_policy": ExistingTextPolicy,
    "existing_output_policy": ExistingOutputPolicy,
    "worker_mode": WorkerMode,
    "theme": Theme,
    "ui_language": UiLanguage,
}
_TUPLE_FIELDS = ("ocr_languages", "previous_suffixes")


def from_json(data: object) -> Settings:
    """Parse a JSON document into validated :class:`Settings` (missing keys use defaults)."""
    if not isinstance(data, Mapping):
        raise SettingsError("document_invalid", type(data).__name__)
    migrated = migrate(data)
    known = {field.name for field in dataclasses.fields(Settings)}
    kwargs: dict[str, Any] = {}
    for key, value in migrated.items():
        if key == "schema_version" or key not in known:
            continue  # unknown keys are ignored for forward compatibility
        if key in _ENUM_FIELDS:
            try:
                value = _ENUM_FIELDS[key](value)
            except ValueError as exc:
                raise SettingsError("choice_invalid", f"{key}={value!r}") from exc
        elif key in _TUPLE_FIELDS:
            if not isinstance(value, list):
                raise SettingsError("list_invalid", key)
            value = tuple(value)
        kwargs[key] = value
    return Settings(**kwargs)
