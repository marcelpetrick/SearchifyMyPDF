# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
import string

import pytest

from searchify_pdf.domain.jobs import JobState, Outcome, Reason
from searchify_pdf.domain.settings import (
    ExistingOutputPolicy,
    ExistingTextPolicy,
    Theme,
    UiLanguage,
    WorkerMode,
)
from searchify_pdf.i18n import MESSAGES, tr


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_every_message_has_both_languages_with_same_placeholders(key: str) -> None:
    entry = MESSAGES[key]
    assert set(entry) == set(UiLanguage)
    assert entry[UiLanguage.ENGLISH] != "" and entry[UiLanguage.GERMAN] != ""
    assert _fields(entry[UiLanguage.ENGLISH]) == _fields(entry[UiLanguage.GERMAN])


def test_all_domain_codes_are_translated() -> None:
    keys = [f"reason.{r.value}" for r in Reason]
    keys += [f"outcome.{o.value}" for o in Outcome]
    keys += [f"state.{s.value}" for s in JobState]
    keys += [f"policy.text.{p.value}" for p in ExistingTextPolicy]
    keys += [f"policy.output.{p.value}" for p in ExistingOutputPolicy]
    keys += [f"workers.{w.value}" for w in WorkerMode]
    keys += [f"theme.{t.value}" for t in Theme]
    missing = [k for k in keys if k not in MESSAGES]
    assert missing == []


def test_tr_formats_and_falls_back() -> None:
    assert tr("button.start") == "Start"
    assert tr("button.start", UiLanguage.GERMAN) == "Starten"
    assert tr("summary.time", UiLanguage.GERMAN, seconds=1.25) == "Dauer: 1.2 s"
    assert tr("no.such.key") == "no.such.key"
