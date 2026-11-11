# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
from typing import Any

import pytest

from searchify_pdf.domain.settings import (
    MAX_FIXED_WORKERS,
    SCHEMA_VERSION,
    ExistingOutputPolicy,
    ExistingTextPolicy,
    Settings,
    SettingsError,
    Theme,
    UiLanguage,
    WorkerMode,
    from_json,
    migrate,
)


def test_defaults_follow_vision() -> None:
    s = Settings()
    assert s.ocr_languages == ("eng", "deu")
    assert s.existing_text_policy is ExistingTextPolicy.NEVER_REPLACE
    assert s.existing_output_policy is ExistingOutputPolicy.ASK
    assert s.output_suffix == "_searchable"
    assert s.worker_mode is WorkerMode.AUTO
    assert s.statistics_enabled is False
    assert s.deskew is False and s.rotate_pages is False
    assert s.ui_language is UiLanguage.ENGLISH
    assert s.theme is Theme.SYSTEM


def test_roundtrip_json() -> None:
    s = Settings(
        ocr_languages=("deu",),
        deskew=True,
        existing_text_policy=ExistingTextPolicy.ASK,
        existing_output_policy=ExistingOutputPolicy.OVERWRITE,
        worker_mode=WorkerMode.FIXED,
        fixed_workers=5,
        statistics_enabled=True,
        theme=Theme.DARK,
        ui_language=UiLanguage.GERMAN,
        timeout_seconds=60,
    )
    data = s.to_json()
    assert data["schema_version"] == SCHEMA_VERSION
    assert from_json(data) == s


def test_from_json_uses_defaults_and_ignores_unknown_keys() -> None:
    assert from_json({"schema_version": SCHEMA_VERSION, "future_key": 1}) == Settings()


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"ocr_languages": ()}, "languages_empty"),
        ({"ocr_languages": ("EN",)}, "language_invalid"),
        ({"ocr_languages": (3,)}, "language_invalid"),
        ({"ocr_languages": ("eng", "eng")}, "language_duplicate"),
        ({"output_suffix": ""}, "suffix_invalid"),
        ({"output_suffix": "a/b"}, "suffix_invalid"),
        ({"output_suffix": "..."}, "suffix_invalid"),
        ({"output_suffix": "_x.pdf"}, "suffix_invalid"),
        ({"output_suffix": 5}, "suffix_invalid"),
        ({"previous_suffixes": ("bad/",)}, "suffix_invalid"),
        ({"fixed_workers": 0}, "workers_out_of_range"),
        ({"fixed_workers": MAX_FIXED_WORKERS + 1}, "workers_out_of_range"),
        ({"fixed_workers": True}, "workers_out_of_range"),
        ({"fixed_workers": 2.5}, "workers_out_of_range"),
        ({"timeout_seconds": 5}, "timeout_out_of_range"),
        ({"timeout_seconds": True}, "timeout_out_of_range"),
        ({"timeout_seconds": 99.0}, "timeout_out_of_range"),
        ({"deskew": "yes"}, "flag_invalid"),
        ({"statistics_enabled": 1}, "flag_invalid"),
        ({"show_window_on_drop": "no"}, "flag_invalid"),
        ({"theme": "dark"}, "choice_invalid"),
        ({"worker_mode": "auto"}, "choice_invalid"),
        ({"existing_text_policy": "ask"}, "choice_invalid"),
        ({"existing_output_policy": "ask"}, "choice_invalid"),
        ({"ui_language": "en"}, "choice_invalid"),
    ],
)
def test_invalid_settings_rejected(changes: dict[str, Any], code: str) -> None:
    with pytest.raises(SettingsError) as info:
        Settings(**changes)
    assert info.value.code == code


def test_bounds_accepted() -> None:
    assert Settings(fixed_workers=1).fixed_workers == 1
    assert Settings(fixed_workers=MAX_FIXED_WORKERS).fixed_workers == MAX_FIXED_WORKERS
    assert Settings(timeout_seconds=30).timeout_seconds == 30
    assert Settings(ocr_languages=("chi_sim",)).ocr_languages == ("chi_sim",)


def test_error_message_contains_detail() -> None:
    err = SettingsError("x", "detail")
    assert str(err) == "x: detail"
    assert str(SettingsError("x")) == "x"


def test_suffix_change_remembers_previous() -> None:
    s = Settings().with_changes(output_suffix="_ocr")
    assert s.previous_suffixes == ("_searchable",)
    s2 = s.with_changes(output_suffix="_searchable")
    assert s2.output_suffix == "_searchable"
    assert s2.previous_suffixes == ("_ocr",)
    assert s2.known_suffixes == ("_searchable", "_ocr")
    assert s2.with_changes(deskew=True).previous_suffixes == ("_ocr",)


def test_suffix_history_is_bounded() -> None:
    s = Settings()
    for i in range(15):
        s = s.with_changes(output_suffix=f"_v{i}")
    assert len(s.previous_suffixes) == 10


def test_migrate_v1() -> None:
    migrated = migrate({"languages": "eng+deu+", "output_suffix": "_ocr"})
    assert migrated["ocr_languages"] == ["eng", "deu"]
    assert migrated["previous_suffixes"] == []
    assert migrated["schema_version"] == SCHEMA_VERSION
    assert from_json({"languages": "deu"}).ocr_languages == ("deu",)


def test_migrate_v1_without_languages() -> None:
    assert "ocr_languages" not in migrate({"schema_version": 1, "languages": 5})


def test_migrate_current_is_identity() -> None:
    data = Settings().to_json()
    assert migrate(data) == data


@pytest.mark.parametrize(
    ("doc", "code"),
    [
        ([], "document_invalid"),
        ({"schema_version": SCHEMA_VERSION + 1}, "schema_too_new"),
        ({"schema_version": "2"}, "schema_invalid"),
        ({"schema_version": True}, "schema_invalid"),
        ({"theme": "neon"}, "choice_invalid"),
        ({"ocr_languages": "eng"}, "list_invalid"),
        ({"fixed_workers": -3}, "workers_out_of_range"),
    ],
)
def test_from_json_errors(doc: object, code: str) -> None:
    with pytest.raises(SettingsError) as info:
        from_json(doc)
    assert info.value.code == code
