# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Engine worker process: runs exactly one OCRmyPDF conversion and exits.

Invoked as ``python -m searchify_pdf.engines.worker '<json>'`` from source installs and
as ``searchify-pdf --searchify-engine-worker '<json>'`` from the frozen application, so
the packaged GUI is never relaunched by accident (VISION §9). The exit code is the
OCRmyPDF exit code; diagnostics go to stderr.
"""

from __future__ import annotations

import json
import sys
from typing import Any

WORKER_FLAG = "--searchify-engine-worker"
OTHER_ERROR = 15


def build_kwargs(request: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "input_file_or_options": request["source"],
        "output_file": request["output"],
        "language": list(request["languages"]),
        "output_type": "pdf",  # ordinary searchable PDF; no Ghostscript/PDF-A needed
        "progress_bar": False,
        "jobs": max(1, int(request.get("page_jobs", 1))),
        "rotate_pages": bool(request.get("rotate_pages", False)),
        # Page workers as threads: Tesseract runs as its own process anyway, and the
        # frozen app then never depends on multiprocessing re-spawning the executable.
        "use_threads": True,
    }
    if request["mode"] == "redo_ocr":
        kwargs["redo_ocr"] = True
    else:
        kwargs["skip_text"] = True
        kwargs["deskew"] = bool(request.get("deskew", False))
    return kwargs


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: worker '<json request>'", file=sys.stderr)
        return 1
    try:
        request = json.loads(argv[0])
        kwargs = build_kwargs(request)
    except (ValueError, KeyError, TypeError) as exc:
        print(f"invalid worker request: {exc}", file=sys.stderr)
        return 1
    import ocrmypdf
    from ocrmypdf.exceptions import ExitCodeException

    try:
        return int(ocrmypdf.ocr(**kwargs))
    except ExitCodeException as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    except Exception as exc:  # report anything else as a failure, never crash silently
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return OTHER_ERROR


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
