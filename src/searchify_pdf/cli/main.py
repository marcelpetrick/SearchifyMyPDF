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
import contextlib
import getpass
import os
import signal
import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from types import FrameType
from typing import TextIO

from searchify_pdf import APP_ID, __version__
from searchify_pdf.application.discovery import discover
from searchify_pdf.application.workflow import BatchRunner, Choice, Decision, PasswordAnswer
from searchify_pdf.domain.jobs import BatchSummary, JobEvent, JobState, Outcome, Reason
from searchify_pdf.domain.settings import (
    MAX_FIXED_WORKERS,
    ExistingOutputPolicy,
    ExistingTextPolicy,
    Settings,
    SettingsError,
    UiLanguage,
    WorkerMode,
)
from searchify_pdf.domain.text_quality import UNKNOWN, TextQuality
from searchify_pdf.engines.base import OcrEngine
from searchify_pdf.engines.pdf_inspect import (
    PdfInfo,
    PdfInspectionError,
    has_marker,
    inspect_pdf,
)
from searchify_pdf.i18n import quality_text, tr
from searchify_pdf.platform.app_location import HOME_OVERRIDE
from searchify_pdf.platform.components import load_inventory
from searchify_pdf.platform.console import is_terminal
from searchify_pdf.platform.desktop import (
    default_data_home,
    install_desktop_entry,
    launch_command,
)
from searchify_pdf.platform.updates import UpdateCheck, UpdateStatus, check_for_update
from searchify_pdf.storage.settings_location import (
    Location,
    SettingsHome,
    current_settings_home,
    store_settings,
)
from searchify_pdf.storage.settings_repository import (
    SETTINGS_FILE_NAME,
    LoadStatus,
    SettingsRepository,
    SettingsSaveError,
)
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
    parser.add_argument(
        "--password-file",
        type=Path,
        help="file with one password per line, tried on password-protected PDFs "
        "(the copy keeps the password); avoids prompts, e.g. in Docker",
    )
    parser.add_argument(
        "--cross-check",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="with 'ask' for existing text: first compare up to 3 pages with a fresh "
        "recognition and show how well they agree (default on)",
    )
    parser.add_argument(
        "--check-text",
        action="store_true",
        help="only report how good the existing text of each PDF is (compared with a "
        "fresh recognition of up to 3 pages); writes nothing",
    )
    parser.add_argument(
        "--process-restricted",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="also process PDFs with usage restrictions (owner password); the copy keeps them",
    )
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
    parser.add_argument(
        "--check-update",
        action="store_true",
        help="ask GitHub whether a newer release exists (one HTTPS request; nothing is "
        "downloaded or installed)",
    )
    parser.add_argument("--gui-smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--install-desktop-entry",
        action="store_true",
        help="add a Linux app-menu launcher that accepts dropped PDFs and folders",
    )
    parser.add_argument(
        "--store-settings-in-profile",
        action="store_true",
        help="opt in: save the settings (with any options given) to your user profile "
        "folder and use them from there; a settings file next to the app still wins",
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
    if args.process_restricted is not None:
        changes["process_restricted_pdfs"] = args.process_restricted
    if args.cross_check is not None:
        changes["cross_check_existing_text"] = args.cross_check
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


def read_password_file(path: Path) -> tuple[str, ...]:
    """One password per line; only the line break is removed, empty lines are ignored."""
    text = path.read_text(encoding="utf-8")
    return tuple(line for line in text.splitlines() if line)


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

    def _read_secret(self, prompt: str) -> str:
        """Hidden input on a real terminal; plain line input otherwise (EOFError on end)."""
        if is_terminal(self.stdin):
            return getpass.getpass(prompt, stream=self.stdout)
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if line == "":
            raise EOFError
        return line.rstrip("\r\n")

    def password(self, source: Path, retry: bool) -> PasswordAnswer | None:
        key = "ask.password.retry" if retry else "ask.password.text"
        self.stdout.write(tr(key, self.language, name=source.name) + "\n")
        try:
            secret = self._read_secret(tr("ask.password.prompt", self.language))
        except EOFError:
            self.stdout.write("\n")
            return PasswordAnswer(Choice.CANCEL)
        if secret == "":
            return PasswordAnswer(Choice.NO)
        return PasswordAnswer(Choice.YES, secret)

    def existing_text(
        self,
        source: Path,
        text_pages: int,
        total_pages: int,
        quality: TextQuality | None = None,
    ) -> Decision | None:
        text = tr(
            "ask.text.text",
            self.language,
            name=source.name,
            text_pages=text_pages,
            pages=total_pages,
        )
        if quality is not None:
            text += "\n" + quality_text(quality, self.language)
        return self._ask(text)


def _inspect_with(source: Path, passwords: Sequence[str]) -> PdfInfo:
    """Inspect ``source``, trying the given passwords on a password-protected PDF."""
    try:
        return inspect_pdf(source)
    except PdfInspectionError as error:
        if error.reason is not Reason.PASSWORD_REQUIRED:
            raise
        last = error
    for password in passwords:
        try:
            return inspect_pdf(source, password)
        except PdfInspectionError as error:
            if error.reason not in {Reason.PASSWORD_REQUIRED, Reason.WRONG_PASSWORD}:
                raise
            last = error
    raise last


def check_text(
    settings: Settings,
    paths: Sequence[Path],
    engine: OcrEngine,
    passwords: Sequence[str],
    stdout: TextIO,
) -> int:
    """``--check-text``: report the quality of existing text layers, write nothing (#6)."""
    language = settings.ui_language
    found = discover(paths, settings.output_suffix, settings.known_suffixes, has_marker)
    checker = engine.text_checker(settings.ocr_languages)
    for candidate in found.candidates:
        source = candidate.source
        try:
            info = _inspect_with(source, passwords)
        except PdfInspectionError as error:
            line = tr(f"reason.{error.reason.value}", language)
        else:
            if not info.any_text:
                line = tr("check.no_text", language)
            else:
                quality = checker(source, info) if checker else UNKNOWN
                line = tr(
                    "check.line",
                    language,
                    text_pages=info.text_page_count,
                    pages=info.page_count,
                    quality=quality_text(quality, language),
                )
        stdout.write(f"{source}: {line}\n")
    for omission in found.omissions:
        stdout.write(f"{omission.path}: {tr(f'reason.{omission.reason.value}', language)}\n")
    return EXIT_OK


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


CANCEL_SIGNALS = (signal.SIGINT, signal.SIGTERM)


@contextlib.contextmanager
def cancel_on_signals(cancel: threading.Event, stdout: TextIO) -> Iterator[None]:
    """Map SIGINT/SIGTERM to a clean batch cancel while the block runs.

    The first signal sets ``cancel`` (queued jobs are cancelled, running engine process
    groups are terminated, staging files discarded); a second one interrupts at once.
    Needed because engine workers run in their own sessions (Ctrl+C does not reach them)
    and because, as PID 1 in a container, Python ignores an unhandled SIGTERM.
    Outside the main thread signal handlers cannot be installed; then nothing changes.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def handler(signum: int, _frame: FrameType | None) -> None:
        if cancel.is_set():
            raise KeyboardInterrupt
        cancel.set()
        stdout.write(f"\n{signal.Signals(signum).name}: cancelling…\n")
        stdout.flush()

    previous = {sig: signal.signal(sig, handler) for sig in CANCEL_SIGNALS}
    try:
        yield
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


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
    passwords: Sequence[str] = (),
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
    cancel = cancel or threading.Event()
    runner = BatchRunner(
        settings,
        engine,
        decisions=decisions,
        on_event=on_event,
        cancel=cancel,
        version=__version__,
        passwords=passwords,
    )
    with cancel_on_signals(cancel, stdout):
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


def store_in_profile(settings: Settings, home: SettingsHome, stdout: TextIO) -> int:
    """``--store-settings-in-profile``: the explicit opt-in of ADR 0012."""
    language = settings.ui_language
    if home.location is Location.OVERRIDE:
        sys.stderr.write(tr("settings.profile.overridden", language, variable=HOME_OVERRIDE))
        sys.stderr.write("\n")
        return EXIT_USAGE
    try:
        store_settings(home.profile_dir, settings)
    except (SettingsSaveError, OSError) as exc:
        code = exc.code if isinstance(exc, SettingsSaveError) else type(exc).__name__
        sys.stderr.write(tr("settings.save_failed", language, code=code) + "\n")
        return EXIT_FAILED
    stdout.write(tr("settings.profile.stored", language, folder=home.profile_dir) + "\n")
    if (home.app_dir / SETTINGS_FILE_NAME).exists():
        stdout.write(tr("settings.profile.shadowed", language, folder=home.app_dir) + "\n")
    return EXIT_OK


def report_update(result: UpdateCheck, language: UiLanguage, stdout: TextIO) -> int:
    """Print the update check; exit 0 when it worked (newer or not), 1 when it failed."""
    if result.status is UpdateStatus.NEWER:
        text = tr(
            "update.cli.newer", language, latest=result.latest, current=__version__, url=result.url
        )
    elif result.status is UpdateStatus.CURRENT:
        text = tr("update.current", language, version=__version__)
    else:
        text = tr("update.failed", language, error=result.error)
    stdout.write(f"{text}\n")
    return EXIT_FAILED if result.status is UpdateStatus.FAILED else EXIT_OK


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
    update_checker: Callable[[], UpdateCheck] = check_for_update,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    home = current_settings_home()
    app_dir = home.directory

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

    if args.store_settings_in_profile:
        return store_in_profile(settings, home, stdout)
    if args.check_update:
        return report_update(update_checker(), settings.ui_language, stdout)
    if args.gui_smoke_test:
        from searchify_pdf.ui.app import smoke_test

        return smoke_test(settings, list(args.paths), app_dir)
    use_gui = not args.check_text and (args.gui or (not args.cli and gui_available(os.environ)))
    if use_gui:
        if gui_launcher is None:
            from searchify_pdf.ui.app import run_gui

            gui_launcher = run_gui
        return gui_launcher(settings, list(args.paths), app_dir)
    if not args.paths:
        parser.print_help(stdout)
        return EXIT_USAGE
    passwords: tuple[str, ...] = ()
    if args.password_file is not None:
        try:
            passwords = read_password_file(args.password_file)
        except (OSError, UnicodeDecodeError) as exc:
            sys.stderr.write(f"{APP_ID}: cannot read --password-file: {exc}\n")
            return EXIT_USAGE
    if args.check_text:
        return check_text(settings, args.paths, engine_factory(), passwords, stdout)
    interactive = not args.non_interactive and is_terminal(stdin)
    return run_headless(
        settings,
        args.paths,
        engine=engine_factory(),
        interactive=interactive,
        app_dir=app_dir,
        stdin=stdin,
        stdout=stdout,
        passwords=passwords,
    )
