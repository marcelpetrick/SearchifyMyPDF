# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Process entry point for ``searchify-pdf``, ``python -m searchify_pdf`` and the frozen app.

The engine-worker and PDF-service flags are handled first, before any UI import, so the
packaged executable can run its child processes without relaunching the GUI.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    from searchify_pdf.engines.worker import WORKER_FLAG

    if args[:1] == [WORKER_FLAG]:
        from searchify_pdf.engines import worker

        return worker.main(args[1:])
    if args[:1] == ["--searchify-pdf-service"]:  # pdf_service.SERVICE_FLAG, kept import-free
        from searchify_pdf.engines import pdf_service

        return pdf_service.main()
    if getattr(sys, "frozen", False):
        from searchify_pdf.platform.runtime import configure_bundled_runtime

        bundle = getattr(sys, "_MEIPASS", None)
        configure_bundled_runtime(os.environ, Path(bundle) if bundle else None)
    from searchify_pdf.cli.main import main as cli_main

    return cli_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
