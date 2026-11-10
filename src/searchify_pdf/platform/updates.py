# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""User-triggered update check (#2, stage 1; ADR 0014).

Only runs when the user asks ("Check for updates" in About, ``--check-update``): one
HTTPS GET of the public GitHub "latest release" endpoint, no account, no identifiers
beyond a generic ``searchify-pdf/<version>`` User-Agent. Drafts and pre-releases are
never offered (the endpoint excludes them). Nothing is downloaded or replaced: a newer
version is reported with its release page, which the user opens and downloads from.

TLS uses the operating system's certificate store (``truststore``), so the frozen
executables verify GitHub's certificate like a browser on the same machine would.
"""

from __future__ import annotations

import dataclasses
import enum
import http.client
import json
import re
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable

from searchify_pdf import APP_ID, __version__

REPOSITORY = "marcelpetrick/SearchifyMyPDF"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 1_000_000

_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


class UpdateStatus(enum.Enum):
    NEWER = "newer"
    CURRENT = "current"
    FAILED = "failed"


@dataclasses.dataclass(frozen=True, slots=True)
class UpdateCheck:
    status: UpdateStatus
    latest: str = ""
    url: str = RELEASES_PAGE
    error: str = ""


def parse_version(text: str) -> tuple[int, int, int] | None:
    """``0.21.2`` or ``v0.21.2`` → ``(0, 21, 2)``; pre-release tags and others → None."""
    match = _VERSION.fullmatch(text.strip())
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def _tls_context() -> ssl.SSLContext:
    import truststore

    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def fetch_latest(
    urlopen: Callable[..., http.client.HTTPResponse] = urllib.request.urlopen,
) -> bytes:
    """The raw JSON of the latest published release (bounded size)."""
    request = urllib.request.Request(
        RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_ID}/{__version__}",
        },
    )
    with urlopen(request, timeout=TIMEOUT_SECONDS, context=_tls_context()) as response:
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("answer too large")
    return payload


def evaluate(current: str, payload: bytes) -> UpdateCheck:
    """Compare ``current`` with the release described by ``payload``."""
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("unexpected answer")
    tag = data.get("tag_name")
    latest = parse_version(tag) if isinstance(tag, str) else None
    installed = parse_version(current)
    if latest is None or installed is None:
        raise ValueError(f"unexpected version {tag!r}")
    page = data.get("html_url")
    # Only ever offer this project's own release pages.
    url = (
        page
        if isinstance(page, str) and page.startswith(f"{RELEASES_PAGE}/tag/")
        else RELEASES_PAGE
    )
    status = UpdateStatus.NEWER if latest > installed else UpdateStatus.CURRENT
    return UpdateCheck(status, ".".join(map(str, latest)), url)


def check_for_update(
    current: str = __version__, fetch: Callable[[], bytes] = fetch_latest
) -> UpdateCheck:
    """Never raises: any network, TLS or format problem becomes ``FAILED``."""
    try:
        return evaluate(current, fetch())
    except (OSError, ValueError, http.client.HTTPException) as exc:
        cause: object = exc
        if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
            cause = exc.reason  # "Name or service not known", not "<urlopen error …>"
        return UpdateCheck(UpdateStatus.FAILED, error=str(cause) or type(cause).__name__)
