# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
import re

import searchify_pdf


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", searchify_pdf.__version__)


def test_identity() -> None:
    assert searchify_pdf.APP_ID == "searchify-pdf"
    assert searchify_pdf.APP_NAME == "Searchify PDF"
