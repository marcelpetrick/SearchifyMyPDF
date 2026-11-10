# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""User-triggered update check (#2, stage 1): no network in these tests."""

from __future__ import annotations

import http.client
import io
import json
import ssl
import urllib.error
from typing import Any

import pytest

from searchify_pdf import __version__
from searchify_pdf.platform import updates
from searchify_pdf.platform.updates import (
    RELEASES_API,
    RELEASES_PAGE,
    UpdateCheck,
    UpdateStatus,
    check_for_update,
    evaluate,
    fetch_latest,
    parse_version,
)

TAG_PAGE = f"{RELEASES_PAGE}/tag/v9.0.0"


def release(tag: object = "v9.0.0", page: object = TAG_PAGE) -> bytes:
    return json.dumps({"tag_name": tag, "html_url": page}).encode()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.21.2", (0, 21, 2)),
        ("v1.2.3", (1, 2, 3)),
        (" v10.0.11 ", (10, 0, 11)),
        ("v1.2.3-alpha.1", None),
        ("1.2", None),
        ("latest", None),
    ],
)
def test_parse_version(text: str, expected: tuple[int, int, int] | None) -> None:
    assert parse_version(text) == expected


def test_newer_release_offers_its_own_page() -> None:
    assert evaluate("0.21.2", release()) == UpdateCheck(UpdateStatus.NEWER, "9.0.0", TAG_PAGE)


@pytest.mark.parametrize("tag", ["v0.21.2", "0.21.2", "v0.9.9", "v0.21.1"])
def test_same_or_older_release_is_current(tag: str) -> None:
    result = evaluate("0.21.2", release(tag))
    assert result.status is UpdateStatus.CURRENT
    assert result.latest == tag.removeprefix("v")


def test_numeric_not_lexical_comparison() -> None:
    assert evaluate("0.9.0", release("v0.10.0")).status is UpdateStatus.NEWER


@pytest.mark.parametrize(
    "page",
    [None, 5, "https://evil.example/releases/tag/v9.0.0", f"{RELEASES_PAGE}x/tag/v9"],
)
def test_foreign_or_missing_page_falls_back_to_the_releases_page(page: object) -> None:
    assert evaluate("0.1.0", release(page=page)).url == RELEASES_PAGE


@pytest.mark.parametrize(
    "payload",
    [b"not json", b"[]", release(tag=None), release(tag="v1.0.0-rc.1"), release(tag=7)],
)
def test_unexpected_answers_are_rejected(payload: bytes) -> None:
    with pytest.raises(ValueError):
        evaluate("0.1.0", payload)


def test_unparsable_installed_version_is_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate("dev", release())


def _failing(exc: Exception) -> Any:
    def fetch() -> bytes:
        raise exc

    return fetch


@pytest.mark.parametrize(
    ("exc", "text"),
    [
        (urllib.error.URLError("offline"), "offline"),
        (urllib.error.URLError(OSError(-3, "name resolution")), "[Errno -3] name resolution"),
        (urllib.error.HTTPError(RELEASES_API, 403, "rate limit", {}, None), "HTTP Error 403"),  # type: ignore[arg-type]
        (ssl.SSLCertVerificationError("bad cert"), "bad cert"),
        (TimeoutError(), "TimeoutError"),
        (http.client.RemoteDisconnected("closed"), "closed"),
        (http.client.IncompleteRead(b""), "IncompleteRead"),
    ],
)
def test_check_never_raises(exc: Exception, text: str) -> None:
    result = check_for_update("0.1.0", _failing(exc))
    assert result.status is UpdateStatus.FAILED
    assert text in result.error


def test_check_reports_garbled_answers_and_uses_the_running_version() -> None:
    garbled = check_for_update("0.1.0", lambda: b"<html>")
    assert garbled.status is UpdateStatus.FAILED and garbled.url == RELEASES_PAGE
    assert __version__ != "9.0.0"
    assert check_for_update(fetch=release).status is UpdateStatus.NEWER


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def test_fetch_latest_sends_a_generic_request() -> None:
    seen: dict[str, Any] = {}

    def urlopen(request: Any, **kwargs: Any) -> _Response:
        seen["request"], seen["kwargs"] = request, kwargs
        return _Response(release())

    assert fetch_latest(urlopen) == release()
    request = seen["request"]
    assert request.full_url == RELEASES_API and request.get_method() == "GET"
    assert request.get_header("User-agent") == f"searchify-pdf/{__version__}"
    assert sorted(request.headers) == ["Accept", "User-agent"]  # nothing else is sent
    assert seen["kwargs"]["timeout"] == updates.TIMEOUT_SECONDS
    context = seen["kwargs"]["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_fetch_latest_bounds_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updates, "MAX_RESPONSE_BYTES", 10)
    assert fetch_latest(lambda *a, **k: _Response(b"x" * 10)) == b"x" * 10
    with pytest.raises(ValueError, match="too large"):
        fetch_latest(lambda *a, **k: _Response(b"x" * 11))
