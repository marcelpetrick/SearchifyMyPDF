# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Command-line interface and launch dispatch.

* ``searchify-pdf`` with no paths opens the desktop UI.
* ``searchify-pdf FILE|FOLDER…`` (what a desktop drop/“Open with” delivers) opens the
  UI and starts immediately with the saved settings.
* ``--cli`` (or no display / no Qt) processes headlessly, printing a summary.

Exit codes: 0 success · 1 some documents failed or were cancelled · 2 usage error ·
3 a decision is required (an "Ask me" policy in a non-interactive run).
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from searchify_pdf import APP_ID, __version__
from searchify_pdf.application.workflow import BatchRunner, Choice, Decision
from searchify_pdf.domain.jobs import BatchSummary, JobEvent, JobState, Outcome
from searchify_pdf.domain.settings import (
    MAX_FIXED_WORKERS,
    ExistingOutputPolicy,
    ExistingTextPolicy,
    Settings,
    SettingsError,
    UiLanguage,
    WorkerMode,
)
from searchify_pdf.engines.base import OcrEngine
from searchify_pdf.i18n import tr
from searchify_pdf.platform.app_location import current_application_directory
from searchify_pdf.platform.components import load_inventory
from searchify_pdf.platform.desktop import (
    default_data_home,
    install_desktop_entry,
    launch_command,
)
from searchify_pdf.storage.settings_repository import LoadStatus, SettingsRepository
from searchify_pdf.storage.statistics import StatisticsRepository

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_ACTION_REQUIRED = 0, 1, 2, 3
OUTPUT_CHOICES = {
    "overwrite": ExistingOutputPolicy.OVERWRITE,
    "skip": ExistingOutputPolicy.NEVER_OVERWRITE,
    "ask": ExistingOutputPolicy.ASK,
}
TEXT_CHOICES = {
    "replace": ExistingTextPolicy.ALWAYS_REPLACE,
    "keep": ExistingTextPolicy.NEVER_REPLACE,
    "ask": ExistingTextPolicy.ASK,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_ID,
        description="Make scanned PDFs searchable. Copies are written next to each original "
        "with a suffix (default: _searchable.pdf); originals are never modified.",
    )
    parser.add_argument("paths", nargs="*", type=Path, help="PDF files and/or folders (recursive)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cli", action="store_true", help="process without opening a window")
    mode.add_argument("--gui", action="store_true", help="always open the window")
    parser.add_argument(
        "--on-existing-output",
        choices=sorted(OUTPUT_CHOICES),
        help="override the saved policy when the copy already exists",
    )
    parser.add_argument(
        "--on-existing-text",
        choices=sorted(TEXT_CHOICES),
        help="override the saved policy when a PDF already contains text",
    )
    parser.add_argument("--languages", help="OCR languages, e.g. eng+deu")
    parser.add_argument(
        "--jobs", help=f"documents at once: auto, 1 (sequential) or 2..{MAX_FIXED_WORKERS}"
    )
    parser.add_argument("--suffix", help="name ending for copies (default _searchable)")
    parser.add_argument("--deskew", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--rotate-pages", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="never prompt; 'Ask me' policies report 'needs a decision' (exit code 3)",
    )
    parser.add_argument("--ui-language", choices=[lang.value for lang in UiLanguage])
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--licenses", action="store_true", help="list bundled components")
    parser.add_argument("--gui-smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--install-desktop-entry",
        action="store_true",
        help="add a Linux app-menu launcher that accepts dropped PDFs and folders",
    )
    return parser


def apply_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    """Per-run overrides; never saved to the settings file."""
    changes: dict[str, object] = {}
    if args.on_existing_output:
        changes["existing_output_policy"] = OUTPUT_CHOICES[args.on_existing_output]
    if args.on_existing_text:
        changes["existing_text_policy"] = TEXT_CHOICES[args.on_existing_text]
    if args.languages:
        changes["ocr_languages"] = tuple(p for p in args.languages.split("+") if p)
    if args.suffix:
        changes["output_suffix"] = args.suffix
    if args.deskew is not None:
        changes["deskew"] = args.deskew
    if args.rotate_pages is not None:
        changes["rotate_pages"] = args.rotate_pages
    if args.ui_language:
        changes["ui_language"] = UiLanguage(args.ui_language)
    if args.jobs:
        if args.jobs == "auto":
            changes["worker_mode"] = WorkerMode.AUTO
        elif args.jobs == "1":
            changes["worker_mode"] = WorkerMode.SEQUENTIAL
        else:
            try:
                count = int(args.jobs)
            except ValueError as exc:
                raise SettingsError("workers_out_of_range", args.jobs) from exc
            changes["worker_mode"] = WorkerMode.FIXED
            changes["fixed_workers"] = count
    return settings.with_changes(**changes) if changes else settings


class TerminalDecisions:
    """Interactive prompts on a terminal: [y]es / [n]o / [a]ll yes / [s]kip all / [c]ancel."""

    def __init__(self, language: UiLanguage, stdin: TextIO, stdout: TextIO) -> None:
        self.language, self.stdin, self.stdout = language, stdin, stdout

    def _ask(self, text: str) -> Decision:
        while True:
            self.stdout.write(f"{text}\n[y]es / [n]o / [a]ll yes / [s]kip all / [c]ancel: ")
            self.stdout.flush()
            answer = self.stdin.readline()
            if answer == "":
                return Decision(Choice.CANCEL)
            key = answer.strip().lower()[:1]
            mapping = {
                "y": Decision(Choice.YES),
                "n": Decision(Choice.NO),
                "a": Decision(Choice.YES, apply_to_batch=True),
                "s": Decision(Choice.NO, apply_to_batch=True),
                "c": Decision(Choice.CANCEL),
            }
            if key in mapping:
                return mapping[key]

    def existing_output(self, source: Path, destination: Path) -> Decision | None:
        return self._ask(tr("ask.output.text", self.language, name=destination.name))

    def existing_text(self, source: Path, text_pages: int, total_pages: int) -> Decision | None:
        return self._ask(
            tr(
                "ask.text.text",
                self.language,
                name=source.name,
                text_pages=text_pages,
                pages=total_pages,
            )
        )


def summary_lines(summary: BatchSummary, language: UiLanguage) -> list[str]:
    counts = {outcome.value: summary.count(outcome) for outcome in Outcome}
    lines = []
    if not summary.results and not summary.omissions:
        lines.append(tr("summary.nothing", language))
    lines.append(tr("summary.line", language, **counts))
    for omission in summary.omissions:
        lines.append(f"  - {omission.path}: {tr(f'reason.{omission.reason.value}', language)}")
    if summary.omissions:
        lines.append(tr("summary.omitted", language, count=len(summary.omissions)))
    lines.append(tr("summary.time", language, seconds=summary.wall_seconds))
    if summary.statistics_error:
        lines.append(tr("summary.stats_error", language, error=summary.statistics_error))
    return lines


def exit_code(summary: BatchSummary) -> int:
    if summary.count(Outcome.FAILED) or summary.count(Outcome.CANCELLED):
        return EXIT_FAILED
    if summary.count(Outcome.ACTION_REQUIRED):
        return EXIT_ACTION_REQUIRED
    return EXIT_OK


def run_headless(
    settings: Settings,
    paths: Sequence[Path],
    *,
    engine: OcrEngine,
    interactive: bool,
    app_dir: Path,
    stdin: TextIO,
    stdout: TextIO,
    cancel: threading.Event | None = None,
) -> int:
    language = settings.ui_language

    def on_event(event: JobEvent) -> None:
        if event.state is JobState.FINISHED and event.result is not None:
            result = event.result
            label = tr(f"outcome.{result.outcome.value}", language)
            reason = tr(f"reason.{result.reason.value}", language)
            target = result.destination or result.source
            stdout.write(f"[{label}] {target} — {reason}\n")
            for note in result.notes:
                stdout.write(f"    note: {tr(f'reason.{note.value}', language)}\n")
            stdout.flush()

    decisions = TerminalDecisions(language, stdin, stdout) if interactive else None
    runner = BatchRunner(
        settings,
        engine,
        decisions=decisions,
        on_event=on_event,
        cancel=cancel,
        version=__version__,
    )
    summary = runner.run(paths)
    if settings.statistics_enabled:
        error = StatisticsRepository(app_dir).record_batch(summary, settings.ocr_languages)
        if error:
            summary = BatchSummary(
                summary.results, summary.omissions, summary.wall_seconds, summary.workers, error
            )
    for line in summary_lines(summary, language):
        stdout.write(line + "\n")
    return exit_code(summary)


def gui_available(env: dict[str, str] | os._Environ[str], platform: str = sys.platform) -> bool:
    if platform.startswith("linux") and not (
        env.get("DISPLAY") or env.get("WAYLAND_DISPLAY") or env.get("QT_QPA_PLATFORM")
    ):
        return False
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


def _default_engine() -> OcrEngine:
    from searchify_pdf.engines.ocrmypdf_engine import OcrmypdfEngine

    return OcrmypdfEngine()


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    engine_factory: Callable[[], OcrEngine] = _default_engine,
    gui_launcher: Callable[[Settings, list[Path], Path], int] | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    app_dir = current_application_directory()

    if args.licenses:
        for component in load_inventory():
            stdout.write(f"{component.name} {component.version} — {component.license}\n")
        return EXIT_OK
    if args.install_desktop_entry:
        command = launch_command(
            frozen=bool(getattr(sys, "frozen", False)),
            executable=sys.executable,
            appimage=os.environ.get("APPIMAGE"),
        )
        entry = install_desktop_entry(default_data_home(os.environ), command)
        stdout.write(f"{entry}\n")
        return EXIT_OK

    loaded = SettingsRepository(app_dir).load()
    if loaded.status is LoadStatus.MALFORMED:
        stdout.write(tr("settings.malformed", loaded.settings.ui_language, error=loaded.error))
        stdout.write("\n")
    try:
        settings = apply_overrides(loaded.settings, args)
    except SettingsError as exc:
        parser.print_usage(sys.stderr)
        sys.stderr.write(f"{APP_ID}: invalid option: {exc}\n")
        return EXIT_USAGE

    if args.gui_smoke_test:
        from searchify_pdf.ui.app import smoke_test

        return smoke_test(settings, list(args.paths), app_dir)
    use_gui = args.gui or (not args.cli and gui_available(os.environ))
    if use_gui:
        if gui_launcher is None:
            from searchify_pdf.ui.app import run_gui

            gui_launcher = run_gui
        return gui_launcher(settings, list(args.paths), app_dir)
    if not args.paths:
        parser.print_help(stdout)
        return EXIT_USAGE
    interactive = not args.non_interactive and stdin.isatty()
    return run_headless(
        settings,
        args.paths,
        engine=engine_factory(),
        interactive=interactive,
        app_dir=app_dir,
        stdin=stdin,
        stdout=stdout,
    )
