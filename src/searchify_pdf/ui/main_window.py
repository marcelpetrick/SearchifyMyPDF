# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""Main window: convert, settings, statistics and about (VISION §3.3, §6)."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from searchify_pdf import APP_NAME, __version__
from searchify_pdf.application.scheduler import auto_documents, system_resources
from searchify_pdf.application.workflow import Choice, Decision, PasswordAnswer
from searchify_pdf.domain.jobs import BatchSummary, JobEvent, JobState, Outcome
from searchify_pdf.domain.settings import (
    MAX_FIXED_WORKERS,
    ExistingOutputPolicy,
    ExistingTextPolicy,
    Settings,
    SettingsError,
    Theme,
    UiLanguage,
    WorkerMode,
)
from searchify_pdf.domain.text_quality import TextQuality
from searchify_pdf.engines.base import OcrEngine
from searchify_pdf.i18n import quality_text, tr
from searchify_pdf.platform.components import load_inventory
from searchify_pdf.platform.desktop import (
    default_data_home,
    install_desktop_entry,
    launch_command,
    open_folder,
)
from searchify_pdf.storage.settings_location import Location, SettingsHome, store_settings
from searchify_pdf.storage.settings_repository import (
    LoadStatus,
    SettingsRepository,
    SettingsSaveError,
)
from searchify_pdf.storage.statistics import StatisticsError, StatisticsRepository, describe
from searchify_pdf.ui.batch_thread import BatchThread
from searchify_pdf.ui.theme import apply_theme

KNOWN_LANGUAGES = ("eng", "deu")
COL_FILE, COL_FOLDER, COL_STATUS, COL_DETAILS = range(4)
OUTCOME_MARK = {
    Outcome.CONVERTED: "✔",
    Outcome.PRESERVED: "✔",
    Outcome.SKIPPED: "↷",
    Outcome.FAILED: "✖",
    Outcome.CANCELLED: "■",
    Outcome.ACTION_REQUIRED: "?",
}


def named[W: QWidget](widget: W, name: str) -> W:
    """Set the object name (used by the stylesheet and by UI tests)."""
    widget.setObjectName(name)
    return widget


def _paths_from_urls(urls: Iterable[QUrl]) -> list[Path]:
    return [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]


class DropZone(QFrame):
    """Accepts dropped files/folders inside the window (distinct from an icon drop)."""

    def __init__(self, on_drop: Callable[[list[Path]], None]) -> None:
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self._on_drop = on_drop
        layout = QVBoxLayout(self)
        self.hint = named(QLabel(alignment=Qt.AlignmentFlag.AlignCenter), "dropHint")
        self.subhint = named(QLabel(alignment=Qt.AlignmentFlag.AlignCenter), "dropSubhint")
        self.subhint.setWordWrap(True)
        layout.addWidget(self.hint)
        layout.addWidget(self.subhint)

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self._set_active(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QEvent) -> None:
        self._set_active(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_active(False)
        paths = _paths_from_urls(event.mimeData().urls())
        if paths:
            event.acceptProposedAction()
            self._on_drop(paths)


class MainWindow(QMainWindow):
    def __init__(
        self,
        repository: SettingsRepository,
        engine_factory: Callable[[], OcrEngine],
        *,
        run_overrides: Settings | None = None,
        app_dir: Path | None = None,
        home: SettingsHome | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.home = home  # None: no switching between portable and profile settings
        self.app_dir = app_dir or repository.directory
        self.engine_factory = engine_factory
        self.stats_repo = StatisticsRepository(self.app_dir)
        loaded = repository.load()
        self.saved = loaded.settings
        self.fingerprint = loaded.fingerprint
        self.load_status = loaded.status
        self.load_error = loaded.error
        self.run_overrides = run_overrides
        self.queue: list[Path] = []
        self.batch_paths: list[Path] = []  # the paths handed to the running batch
        self.autostart_pending = False  # an OS open event arrived during a run
        self.batch: BatchThread | None = None
        self.rows: dict[int, int] = {}
        self.total = 0
        self.finished_count = 0
        self.workers = 0
        self.last_summary: BatchSummary | None = None
        self.prompter: Callable[[str, dict[str, object]], Decision | PasswordAnswer] = (
            self._prompt_dialog
        )
        self.message: Callable[..., QMessageBox.StandardButton] = self._message_box
        self.file_picker: Callable[[], list[str]] = self._pick_files
        self.folder_picker: Callable[[], str] = self._pick_folder
        self.folder_opener: Callable[[Path], None] = open_folder
        self._updating_form = False

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(980, 700)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._build_convert_tab()
        self._build_settings_tab()
        self._build_stats_tab()
        self._build_about_tab()
        self._build_actions()
        self._load_form(self.saved)
        self.retranslate()
        self._update_buttons()

    # ------------------------------------------------------------------ properties
    @property
    def lang(self) -> UiLanguage:
        return self.saved.ui_language

    def t(self, key: str, **values: object) -> str:
        return tr(key, self.lang, **values)

    @property
    def running(self) -> bool:
        return self.batch is not None

    # ------------------------------------------------------------------ building
    def _build_convert_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        header = QHBoxLayout()
        self.title = named(QLabel(APP_NAME), "title")
        self.tagline = named(QLabel(), "tagline")
        header.addWidget(self.title)
        header.addSpacing(12)
        header.addWidget(self.tagline, 1)
        layout.addLayout(header)
        self.drop_zone = DropZone(self.add_paths)
        layout.addWidget(self.drop_zone)

        buttons = QHBoxLayout()
        self.add_files_button = named(QPushButton(), "addFiles")
        self.add_folder_button = named(QPushButton(), "addFolder")
        self.clear_button = named(QPushButton(), "clear")
        self.start_button = named(QPushButton(), "primary")
        self.cancel_button = named(QPushButton(), "cancel")
        self.open_button = named(QPushButton(), "openFolder")
        self.add_files_button.clicked.connect(self.choose_files)
        self.add_folder_button.clicked.connect(self.choose_folder)
        self.clear_button.clicked.connect(self.clear_queue)
        self.start_button.clicked.connect(self.start)
        self.cancel_button.clicked.connect(self.cancel)
        self.open_button.clicked.connect(self.open_result_folder)
        for button in (self.add_files_button, self.add_folder_button, self.clear_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        for button in (self.open_button, self.cancel_button, self.start_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.table = QTableWidget(0, 4)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(COL_FOLDER, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)  # the status line below carries the numbers
        self.progress.setFixedHeight(10)
        layout.addWidget(self.progress)
        self.status_label = named(QLabel(), "hint")
        self.summary_label = named(QLabel(), "summary")
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status_label)
        layout.addWidget(self.summary_label)
        self.tabs.addTab(page, "")

    def _build_settings_tab(self) -> None:
        page = QWidget()
        outer = QVBoxLayout(page)
        self.settings_notice = named(QLabel(), "warning")
        self.settings_notice.setWordWrap(True)
        outer.addWidget(self.settings_notice)

        self.group_recognition = QGroupBox()
        form = QFormLayout(self.group_recognition)
        lang_row = QHBoxLayout()
        self.language_boxes: dict[str, QCheckBox] = {}
        for code in KNOWN_LANGUAGES:
            box = named(QCheckBox(), f"lang_{code}")
            box.toggled.connect(self._form_changed)
            self.language_boxes[code] = box
            lang_row.addWidget(box)
        lang_row.addStretch(1)
        self.languages_label = QLabel()
        form.addRow(self.languages_label, lang_row)
        self.languages_hint = named(QLabel(), "hint")
        form.addRow("", self.languages_hint)
        self.deskew_box = named(QCheckBox(), "deskew")
        self.rotate_box = named(QCheckBox(), "rotate")
        for box in (self.deskew_box, self.rotate_box):
            box.toggled.connect(self._form_changed)
            form.addRow("", box)
        self.text_policy_label = QLabel()
        self.text_policy_group = QButtonGroup(self)
        self.text_policy_buttons: dict[ExistingTextPolicy, QRadioButton] = {}
        text_column = QVBoxLayout()
        for policy in (
            ExistingTextPolicy.NEVER_REPLACE,
            ExistingTextPolicy.ASK,
            ExistingTextPolicy.ALWAYS_REPLACE,
        ):
            radio = named(QRadioButton(), f"text_{policy.value}")
            radio.toggled.connect(self._form_changed)
            self.text_policy_group.addButton(radio)
            self.text_policy_buttons[policy] = radio
            text_column.addWidget(radio)
        form.addRow(self.text_policy_label, text_column)
        outer.addWidget(self.group_recognition)

        self.group_files = QGroupBox()
        files_form = QFormLayout(self.group_files)
        self.output_policy_label = QLabel()
        self.output_policy_combo = named(QComboBox(), "outputPolicy")
        for output_policy in (
            ExistingOutputPolicy.ASK,
            ExistingOutputPolicy.OVERWRITE,
            ExistingOutputPolicy.NEVER_OVERWRITE,
        ):
            self.output_policy_combo.addItem("", output_policy.value)
        self.output_policy_combo.currentIndexChanged.connect(self._form_changed)
        files_form.addRow(self.output_policy_label, self.output_policy_combo)
        self.suffix_label = QLabel()
        self.suffix_edit = named(QLineEdit(), "suffix")
        self.suffix_edit.setMaxLength(40)
        self.suffix_edit.textChanged.connect(self._form_changed)
        files_form.addRow(self.suffix_label, self.suffix_edit)
        self.suffix_example = named(QLabel(), "hint")
        files_form.addRow("", self.suffix_example)
        self.cross_check_box = named(QCheckBox(), "crossCheck")
        self.cross_check_box.toggled.connect(self._form_changed)
        form.addRow("", self.cross_check_box)
        self.restricted_box = named(QCheckBox(), "restricted")
        self.restricted_box.toggled.connect(self._form_changed)
        files_form.addRow("", self.restricted_box)
        outer.addWidget(self.group_files)

        self.group_performance = QGroupBox()
        perf_form = QFormLayout(self.group_performance)
        self.workers_label = QLabel()
        self.worker_combo = named(QComboBox(), "workerMode")
        for mode in (WorkerMode.AUTO, WorkerMode.SEQUENTIAL, WorkerMode.FIXED):
            self.worker_combo.addItem("", mode.value)
        self.worker_combo.currentIndexChanged.connect(self._form_changed)
        self.worker_spin = named(QSpinBox(), "workerCount")
        self.worker_spin.setRange(1, MAX_FIXED_WORKERS)
        self.worker_spin.valueChanged.connect(self._form_changed)
        worker_row = QHBoxLayout()
        worker_row.addWidget(self.worker_combo)
        worker_row.addWidget(self.worker_spin)
        worker_row.addStretch(1)
        perf_form.addRow(self.workers_label, worker_row)
        self.worker_hint = named(QLabel(), "hint")
        perf_form.addRow("", self.worker_hint)
        outer.addWidget(self.group_performance)

        self.group_appearance = QGroupBox()
        app_form = QFormLayout(self.group_appearance)
        self.theme_label = QLabel()
        self.theme_combo = named(QComboBox(), "theme")
        for theme in (Theme.SYSTEM, Theme.LIGHT, Theme.DARK):
            self.theme_combo.addItem("", theme.value)
        self.theme_combo.currentIndexChanged.connect(self._form_changed)
        app_form.addRow(self.theme_label, self.theme_combo)
        self.ui_language_label = QLabel()
        self.ui_language_combo = named(QComboBox(), "uiLanguage")
        self.ui_language_combo.addItem("English", UiLanguage.ENGLISH.value)
        self.ui_language_combo.addItem("Deutsch", UiLanguage.GERMAN.value)
        self.ui_language_combo.currentIndexChanged.connect(self._form_changed)
        app_form.addRow(self.ui_language_label, self.ui_language_combo)
        self.stats_box = named(QCheckBox(), "statistics")
        self.stats_box.toggled.connect(self._form_changed)
        app_form.addRow("", self.stats_box)
        outer.addWidget(self.group_appearance)

        row = QHBoxLayout()
        self.settings_status = named(QLabel(), "hint")
        self.settings_status.setWordWrap(True)
        self.revert_button = named(QPushButton(), "revert")
        self.save_button = named(QPushButton(), "primary")
        self.revert_button.clicked.connect(self.revert_settings)
        self.save_button.clicked.connect(self.save_settings)
        row.addWidget(self.settings_status, 1)
        row.addWidget(self.revert_button)
        row.addWidget(self.save_button)
        outer.addLayout(row)
        self.settings_path_label = named(QLabel(), "hint")
        self.settings_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        outer.addWidget(self.settings_path_label)
        location_row = QHBoxLayout()
        self.location_button = named(QPushButton(), "location")
        self.location_button.clicked.connect(self.relocate_settings)
        location_row.addWidget(self.location_button)
        location_row.addStretch(1)
        outer.addLayout(location_row)
        outer.addStretch(1)
        self.tabs.addTab(page, "")

    def _build_stats_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.stats_view = named(QTextBrowser(), "statsView")
        layout.addWidget(self.stats_view, 1)
        self.reset_stats_button = named(QPushButton(), "resetStats")
        self.reset_stats_button.clicked.connect(self.reset_statistics)
        layout.addWidget(self.reset_stats_button, 0, Qt.AlignmentFlag.AlignRight)
        self.tabs.addTab(page, "")

    def _build_about_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.about_label = QLabel()
        self.about_label.setWordWrap(True)
        self.engine_label = named(QLabel(), "hint")
        layout.addWidget(self.about_label)
        layout.addWidget(self.engine_label)
        self.components_label = named(QLabel(), "summary")
        layout.addWidget(self.components_label)
        self.components_table = QTableWidget(0, 4)
        self.components_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.components_table.verticalHeader().setVisible(False)
        self.components_table.horizontalHeader().setStretchLastSection(True)
        self.components_table.setHorizontalHeaderLabels(["Component", "Version", "License", "URL"])
        components = load_inventory()
        self.components_table.setRowCount(len(components))
        for row, component in enumerate(components):
            values = (component.name, component.version, component.license, component.url)
            for col, value in enumerate(values):
                self.components_table.setItem(row, col, QTableWidgetItem(value))
        self.components_table.resizeColumnsToContents()
        layout.addWidget(self.components_table, 1)
        self.launcher_button = named(QPushButton(), "installLauncher")
        self.launcher_button.clicked.connect(self.install_launcher)
        self.launcher_button.setVisible(sys.platform.startswith("linux"))
        layout.addWidget(self.launcher_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.tabs.addTab(page, "")

    def _build_actions(self) -> None:
        bindings: tuple[
            tuple[QKeySequence | QKeySequence.StandardKey, Callable[[], object]], ...
        ] = (
            (QKeySequence.StandardKey.Open, self.choose_files),
            (QKeySequence("Ctrl+Shift+O"), self.choose_folder),
            (QKeySequence("Ctrl+Return"), self.start),
            (QKeySequence(Qt.Key.Key_Escape), self.cancel),
            (QKeySequence.StandardKey.Save, self.save_settings),
        )
        for shortcut, slot in bindings:
            action = QAction(self)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            self.addAction(action)

    # ------------------------------------------------------------------ text
    def retranslate(self) -> None:
        t = self.t
        self.tabs.setTabText(0, t("tab.convert"))
        self.tabs.setTabText(1, t("tab.settings"))
        self.tabs.setTabText(2, t("tab.statistics"))
        self.tabs.setTabText(3, t("tab.about"))
        self.tagline.setText(t("app.tagline"))
        self.drop_zone.hint.setText(t("drop.hint"))
        self.drop_zone.subhint.setText(t("drop.subhint"))
        self.add_files_button.setText(t("button.add_files"))
        self.add_folder_button.setText(t("button.add_folder"))
        self.clear_button.setText(t("button.clear"))
        self.start_button.setText(t("button.start"))
        self.cancel_button.setText(t("button.cancel"))
        self.open_button.setText(t("button.open_folder"))
        self.table.setHorizontalHeaderLabels(
            [t("column.file"), t("column.folder"), t("column.status"), t("column.details")]
        )
        self.group_recognition.setTitle(t("settings.group.recognition"))
        self.group_files.setTitle(t("settings.group.files"))
        self.group_performance.setTitle(t("settings.group.performance"))
        self.group_appearance.setTitle(t("settings.group.appearance").replace("&", "&&"))
        self.languages_label.setText(t("settings.languages"))
        self.languages_hint.setText(t("settings.languages.hint"))
        for code, box in self.language_boxes.items():
            box.setText(t(f"lang.{code}"))
        self.deskew_box.setText(t("settings.deskew"))
        self.rotate_box.setText(t("settings.rotate"))
        self.text_policy_label.setText(t("settings.existing_text"))
        for policy, radio in self.text_policy_buttons.items():
            radio.setText(t(f"policy.text.{policy.value}"))
        self.output_policy_label.setText(t("settings.existing_output"))
        for i in range(self.output_policy_combo.count()):
            value = self.output_policy_combo.itemData(i)
            self.output_policy_combo.setItemText(i, t(f"policy.output.{value}"))
        self.suffix_label.setText(t("settings.suffix"))
        self.restricted_box.setText(t("settings.restricted"))
        self.cross_check_box.setText(t("settings.cross_check"))
        self.workers_label.setText(t("settings.workers"))
        for i in range(self.worker_combo.count()):
            self.worker_combo.setItemText(i, t(f"workers.{self.worker_combo.itemData(i)}"))
        cpu, memory = system_resources()
        self.worker_hint.setText(t("settings.workers.auto_hint", count=auto_documents(cpu, memory)))
        self.theme_label.setText(t("settings.theme"))
        for i in range(self.theme_combo.count()):
            self.theme_combo.setItemText(i, t(f"theme.{self.theme_combo.itemData(i)}"))
        self.ui_language_label.setText(t("settings.ui_language"))
        self.stats_box.setText(t("settings.statistics"))
        self.revert_button.setText(t("button.revert"))
        self.save_button.setText(t("button.save"))
        self.settings_path_label.setText(t("settings.file", path=self.repository.path))
        target = self._relocation_target()
        self.location_button.setVisible(target is not None)
        if target is not None and self.home is not None:
            to_profile = target == self.home.profile_dir
            self.location_button.setText(
                t("button.to_profile" if to_profile else "button.to_portable")
            )
        self.reset_stats_button.setText(t("button.reset_stats"))
        self.about_label.setText(t("about.text", version=__version__))
        self.components_label.setText(t("about.components"))
        self.launcher_button.setText(t("button.install_launcher"))
        self._refresh_engine_label()
        self._update_suffix_example()
        self._refresh_settings_notice()
        self._refresh_status()
        self.refresh_statistics()
        if self.last_summary is not None:
            self._show_summary(self.last_summary)

    def _refresh_engine_label(self) -> None:
        try:
            name = self.engine_factory().capabilities().name
        except Exception as exc:  # engine probing must never break the About page
            name = f"unavailable ({exc})"
        self.engine_label.setText(self.t("about.engine", engine=name))

    # ------------------------------------------------------------------ queue
    def add_paths(self, paths: Iterable[Path]) -> None:
        known = {os.path.abspath(p) for p in self.queue}  # noqa: PTH100 - keep symlink names
        for path in paths:
            key = os.path.abspath(path)  # noqa: PTH100
            if key not in known:
                known.add(key)
                self.queue.append(Path(key))
        if not self.running:
            self._show_queue()
        self._update_buttons()

    def _show_queue(self) -> None:
        self.table.setRowCount(len(self.queue))
        for row, path in enumerate(self.queue):
            self._set_row(row, path, self.t("state.discovered"), "")

    def _set_row(self, row: int, path: Path, status: str, details: str, tooltip: str = "") -> None:
        values = (path.name, str(path.parent), status, details)
        for col, value in enumerate(values):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            item.setText(value)
            item.setToolTip(tooltip if col == COL_DETAILS and tooltip else value)

    def clear_queue(self) -> None:
        if self.running:
            return
        self.queue.clear()
        self.table.setRowCount(0)
        self.summary_label.clear()
        self.last_summary = None
        self._update_buttons()

    def choose_files(self) -> None:
        self.add_paths(Path(p) for p in self.file_picker() if p)

    def choose_folder(self) -> None:
        folder = self.folder_picker()
        if folder:
            self.add_paths([Path(folder)])

    def _pick_files(self) -> list[str]:  # pragma: no cover - native dialog
        files, _ = QFileDialog.getOpenFileNames(
            self, self.t("dialog.pick_files"), str(Path.home()), "PDF (*.pdf *.PDF)"
        )
        return list(files)

    def _pick_folder(self) -> str:  # pragma: no cover - native dialog
        return QFileDialog.getExistingDirectory(
            self, self.t("dialog.pick_folder"), str(Path.home())
        )

    # ------------------------------------------------------------------ running
    def run_settings(self) -> Settings:
        """Immutable snapshot of the *saved* settings (plus launch overrides)."""
        return self.run_overrides or self.saved

    def start(self) -> None:
        if self.running or not self.queue:
            return
        self.rows.clear()
        self.table.setRowCount(0)
        self.summary_label.clear()
        self.last_summary = None
        self.total = 0
        self.finished_count = 0
        self.workers = 0
        snapshot = self.run_settings()
        self.batch_paths = list(self.queue)
        self.autostart_pending = False
        self.batch = BatchThread(snapshot, self.batch_paths, self.engine_factory(), self.prompter)
        self.batch.job_event.connect(self._on_event)
        self.batch.planned.connect(self._on_planned)
        self.batch.done.connect(self._on_done)
        self.batch.start()
        self._update_buttons()
        self._refresh_status()

    def cancel(self) -> None:
        if self.batch is not None:
            self.batch.cancel()
            self.status_label.setText(self.t("progress.cancelling"))

    def _on_planned(self, documents: int) -> None:
        self.workers = documents

    def _on_event(self, event: JobEvent) -> None:
        if event.state is JobState.DISCOVERED:
            self.rows[event.job_id] = self.table.rowCount()
            self.table.insertRow(self.table.rowCount())
            self.total += 1
        row = self.rows.get(event.job_id)
        if row is None:
            return
        if event.result is not None:
            result = event.result
            self.finished_count += 1
            status = f"{OUTCOME_MARK[result.outcome]} {self.t(f'outcome.{result.outcome.value}')}"
            details = self.t(f"reason.{result.reason.value}")
            notes = [self.t(f"reason.{note.value}") for note in result.notes]
            if notes:
                details = " · ".join([details, *notes])
            shown = result.destination or event.source
            tooltip = f"{details}\n{result.detail}" if result.detail else ""
            self._set_row(row, shown, status, details, tooltip)
        else:
            self._set_row(row, event.source, self.t(f"state.{event.state.value}"), "")
        self._refresh_status()

    def _on_done(self, summary: BatchSummary) -> None:
        batch = self.batch
        self.batch = None
        if batch is not None:
            batch.wait()
            batch.deleteLater()
        # decide from the batch's own immutable snapshot, not settings changed meanwhile
        snapshot = batch.settings if batch is not None else self.run_settings()
        if snapshot.statistics_enabled and summary.results:
            error = self.stats_repo.record_batch(summary, snapshot.ocr_languages)
            if error:
                summary = BatchSummary(
                    summary.results, summary.omissions, summary.wall_seconds, summary.workers, error
                )
        self.last_summary = summary
        self.run_overrides = None  # later runs use the saved settings again
        # only the processed paths leave the queue; paths added during the run stay
        done = set(self.batch_paths)
        self.queue = [path for path in self.queue if path not in done]
        self.batch_paths = []
        self._show_summary(summary)
        self._update_buttons()
        self._refresh_status()
        self.refresh_statistics()
        if self.autostart_pending and self.queue:
            self.start()
        self.autostart_pending = False

    def _show_summary(self, summary: BatchSummary) -> None:
        counts = {outcome.value: summary.count(outcome) for outcome in Outcome}
        lines = [f"{self.t('summary.title')}: {self.t('summary.line', **counts)}"]
        if not summary.results and not summary.omissions:
            lines.append(self.t("summary.nothing"))
        if summary.omissions:
            lines.append(self.t("summary.omitted", count=len(summary.omissions)))
            for omission in summary.omissions[:20]:
                lines.append(f"• {omission.path.name}: {self.t(f'reason.{omission.reason.value}')}")
        lines.append(self.t("summary.time", seconds=summary.wall_seconds))
        if self.queue and not self.running:
            lines.append(self.t("summary.queued", count=len(self.queue)))
        if summary.statistics_error:
            lines.append(self.t("summary.stats_error", error=summary.statistics_error))
        self.summary_label.setText("\n".join(lines))

    def open_result_folder(self) -> None:
        if self.last_summary and self.last_summary.folders:
            self.folder_opener(self.last_summary.folders[0])

    def _refresh_status(self) -> None:
        if self.running:
            self.progress.setRange(0, max(1, self.total))
            self.progress.setValue(self.finished_count)
            text = self.t(
                "progress.running",
                done=self.finished_count,
                total=self.total,
                workers=self.workers or "…",
            )
            if self.batch is not None and self.batch.cancel_event.is_set():
                text = self.t("progress.cancelling")
            self.status_label.setText(text)
        else:
            self.progress.setRange(0, 1)
            self.progress.setValue(1 if self.last_summary else 0)
            self.status_label.setText(self.t("progress.idle"))

    def _update_buttons(self) -> None:
        running = self.running
        self.start_button.setEnabled(not running and bool(self.queue))
        self.cancel_button.setEnabled(running)
        self.clear_button.setEnabled(
            not running and (bool(self.queue) or self.last_summary is not None)
        )
        self.add_files_button.setEnabled(True)
        self.add_folder_button.setEnabled(True)
        self.open_button.setEnabled(
            not running and self.last_summary is not None and bool(self.last_summary.folders)
        )

    # ------------------------------------------------------------------ prompts
    def _password_dialog(self, payload: dict[str, object]) -> PasswordAnswer:  # pragma: no cover
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t("ask.password.title"))
        layout = QVBoxLayout(dialog)
        name = Path(str(payload["source"])).name
        key = "ask.password.retry" if payload.get("retry") else "ask.password.text"
        label = QLabel(self.t(key, name=name))
        label.setWordWrap(True)
        layout.addWidget(label)
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setAccessibleName(self.t("ask.password.title"))
        layout.addWidget(field)
        buttons = QDialogButtonBox()
        unlock = buttons.addButton(
            self.t("ask.password.ok"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        skip = buttons.addButton(self.t("ask.no_skip"), QDialogButtonBox.ButtonRole.ActionRole)
        stop = buttons.addButton(self.t("ask.cancel_all"), QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)
        chosen = [Choice.CANCEL]

        def choose(choice: Choice) -> None:
            chosen[0] = choice
            dialog.accept()

        unlock.clicked.connect(lambda: choose(Choice.YES))
        skip.clicked.connect(lambda: choose(Choice.NO))
        stop.clicked.connect(lambda: choose(Choice.CANCEL))
        unlock.setDefault(True)
        field.setFocus()
        dialog.exec()
        if chosen[0] is Choice.YES:
            return PasswordAnswer(Choice.YES, field.text())
        return PasswordAnswer(chosen[0])

    def text_question(self, payload: dict[str, object]) -> str:
        """The existing-text question, with the cross-check result when one ran (#6)."""
        text = self.t(
            "ask.text.text",
            name=Path(str(payload["source"])).name,
            text_pages=payload["text_pages"],
            pages=payload["pages"],
        )
        quality = payload.get("quality")
        if isinstance(quality, TextQuality):
            text += "\n\n" + quality_text(quality, self.lang)
        return text

    def _prompt_dialog(
        self, kind: str, payload: dict[str, object]
    ) -> Decision | PasswordAnswer:  # pragma: no cover
        if kind == "password":
            return self._password_dialog(payload)
        box = QMessageBox(self)
        apply_all = QCheckBox(self.t("ask.apply_all"))
        box.setCheckBox(apply_all)
        if kind == "output":
            box.setWindowTitle(self.t("ask.output.title"))
            box.setText(self.t("ask.output.text", name=Path(str(payload["destination"])).name))
            yes = box.addButton(self.t("ask.yes_replace"), QMessageBox.ButtonRole.YesRole)
            no = box.addButton(self.t("ask.no_skip"), QMessageBox.ButtonRole.NoRole)
        else:
            box.setWindowTitle(self.t("ask.text.title"))
            box.setText(self.text_question(payload))
            yes = box.addButton(self.t("ask.yes_replace"), QMessageBox.ButtonRole.YesRole)
            no = box.addButton(self.t("ask.no_keep"), QMessageBox.ButtonRole.NoRole)
        box.addButton(self.t("ask.cancel_all"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is yes:
            return Decision(Choice.YES, apply_all.isChecked())
        if clicked is no:
            return Decision(Choice.NO, apply_all.isChecked())
        return Decision(Choice.CANCEL)

    def _message_box(  # pragma: no cover - modal native dialog
        self,
        icon: QMessageBox.Icon,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButton,
    ) -> QMessageBox.StandardButton:
        return QMessageBox(icon, title, text, buttons, self).exec()  # type: ignore[return-value]

    # ------------------------------------------------------------------ settings
    def _load_form(self, settings: Settings) -> None:
        self._updating_form = True
        try:
            for code, box in self.language_boxes.items():
                box.setChecked(code in settings.ocr_languages)
            self.deskew_box.setChecked(settings.deskew)
            self.rotate_box.setChecked(settings.rotate_pages)
            self.text_policy_buttons[settings.existing_text_policy].setChecked(True)
            self.output_policy_combo.setCurrentIndex(
                self.output_policy_combo.findData(settings.existing_output_policy.value)
            )
            self.suffix_edit.setText(settings.output_suffix)
            self.restricted_box.setChecked(settings.process_restricted_pdfs)
            self.cross_check_box.setChecked(settings.cross_check_existing_text)
            self.worker_combo.setCurrentIndex(
                self.worker_combo.findData(settings.worker_mode.value)
            )
            self.worker_spin.setValue(settings.fixed_workers)
            self.theme_combo.setCurrentIndex(self.theme_combo.findData(settings.theme.value))
            self.ui_language_combo.setCurrentIndex(
                self.ui_language_combo.findData(settings.ui_language.value)
            )
            self.stats_box.setChecked(settings.statistics_enabled)
        finally:
            self._updating_form = False
        self._form_changed()

    def form_settings(self) -> Settings:
        """Settings currently shown in the form; raises :class:`SettingsError` if invalid."""
        languages = [code for code, box in self.language_boxes.items() if box.isChecked()]
        extra = [lang for lang in self.saved.ocr_languages if lang not in KNOWN_LANGUAGES]
        text_policy = next(
            policy for policy, radio in self.text_policy_buttons.items() if radio.isChecked()
        )
        return self.saved.with_changes(
            ocr_languages=tuple(languages + extra),
            deskew=self.deskew_box.isChecked(),
            rotate_pages=self.rotate_box.isChecked(),
            existing_text_policy=text_policy,
            existing_output_policy=ExistingOutputPolicy(self.output_policy_combo.currentData()),
            output_suffix=self.suffix_edit.text(),
            process_restricted_pdfs=self.restricted_box.isChecked(),
            cross_check_existing_text=self.cross_check_box.isChecked(),
            worker_mode=WorkerMode(self.worker_combo.currentData()),
            fixed_workers=self.worker_spin.value(),
            theme=Theme(self.theme_combo.currentData()),
            ui_language=UiLanguage(self.ui_language_combo.currentData()),
            statistics_enabled=self.stats_box.isChecked(),
        )

    @property
    def dirty(self) -> bool:
        try:
            return self.form_settings() != self.saved
        except SettingsError:
            return True

    def _form_changed(self, *_: object) -> None:
        if self._updating_form:
            return
        self.worker_spin.setEnabled(self.worker_combo.currentData() == WorkerMode.FIXED.value)
        self._update_suffix_example()
        try:
            self.form_settings()
        except SettingsError as exc:
            self.settings_status.setObjectName("error")
            self.settings_status.setText(self.t("settings.invalid", detail=exc.code))
            self.save_button.setEnabled(False)
        else:
            self.settings_status.setObjectName("warning" if self.dirty else "hint")
            self.settings_status.setText(self.t("settings.unsaved") if self.dirty else "")
            self.save_button.setEnabled(self.dirty)
        self.settings_status.style().unpolish(self.settings_status)
        self.settings_status.style().polish(self.settings_status)
        self.revert_button.setEnabled(self.dirty)

    def _update_suffix_example(self) -> None:
        example = f"Scan{self.suffix_edit.text()}.pdf"  # plain text: may be invalid while typing
        self.suffix_example.setText(self.t("settings.suffix.example", example=example))

    def _refresh_settings_notice(self) -> None:
        notices = []
        if self.load_status is LoadStatus.MALFORMED:
            notices.append(self.t("settings.malformed", error=self.load_error))
        in_profile = self.home is not None and self.repository.directory == self.home.profile_dir
        if in_profile:
            notices.append(self.t("settings.profile.in_use", folder=self.repository.directory))
        elif not self.repository.is_writable():
            notices.append(self.t("settings.readonly", folder=self.repository.directory))
        self.settings_notice.setText("\n".join(notices))
        self.settings_notice.setVisible(bool(notices))

    def _relocation_target(self) -> Path | None:
        """Where the location button would move the settings (ADR 0012), if anywhere.

        Offered only when the portable folder cannot be written (→ user profile, the
        explicit opt-in) or when the settings are in the profile and the app folder is
        writable again (→ back next to the app). Never with ``SEARCHIFY_PDF_HOME``.
        """
        home = self.home
        if home is None or home.location is Location.OVERRIDE:
            return None
        current = self.repository.directory
        if current == home.app_dir and not self.repository.is_writable():
            return home.profile_dir
        if current == home.profile_dir and SettingsRepository(home.app_dir).is_writable():
            return home.app_dir
        return None

    def relocate_settings(self) -> bool:
        """Save the form's settings in the other location and use them from there."""
        target = self._relocation_target()
        if target is None or self.home is None:
            return False
        key = "ask.to_profile" if target == self.home.profile_dir else "ask.to_portable"
        answer = self.message(
            QMessageBox.Icon.Question,
            APP_NAME,
            self.t(key, folder=target),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        try:
            new = self.form_settings()
        except SettingsError as exc:
            self.settings_status.setText(self.t("settings.invalid", detail=exc.code))
            return False
        try:
            fingerprint = store_settings(target, new)
        except (SettingsSaveError, OSError) as exc:
            code = exc.code if isinstance(exc, SettingsSaveError) else type(exc).__name__
            text = self.t("settings.save_failed", code=code)
            self.settings_status.setText(text)
            self.message(QMessageBox.Icon.Warning, APP_NAME, text, QMessageBox.StandardButton.Ok)
            return False
        self.repository = SettingsRepository(target)
        self.fingerprint = fingerprint
        self.app_dir = target
        self.stats_repo = StatisticsRepository(target)
        self._apply_saved(new)
        self.settings_status.setText(self.t("settings.saved"))
        return True

    def revert_settings(self) -> None:
        self._load_form(self.saved)

    def save_settings(self) -> bool:
        """Validate and save; on failure keep the unsaved form and report the error."""
        try:
            new = self.form_settings()
        except SettingsError as exc:
            self.settings_status.setText(self.t("settings.invalid", detail=exc.code))
            return False
        try:
            self.fingerprint = self.repository.save(new, self.fingerprint)
        except SettingsSaveError as exc:
            if exc.code == "stale":
                return self._resolve_stale(new)
            if exc.code in {"permission_denied", "read_only"}:
                text = self.t("settings.readonly", folder=self.repository.directory)
            else:
                text = self.t("settings.save_failed", code=exc.code)
            self.settings_status.setObjectName("error")
            self.settings_status.setText(text)
            self.message(QMessageBox.Icon.Warning, APP_NAME, text, QMessageBox.StandardButton.Ok)
            return False
        self._apply_saved(new)
        self.settings_status.setText(self.t("settings.saved"))
        return True

    def _resolve_stale(self, new: Settings) -> bool:
        answer = self.message(
            QMessageBox.Icon.Question,
            APP_NAME,
            self.t("settings.stale"),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Reset
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Reset:
            loaded = self.repository.load()
            self.fingerprint = loaded.fingerprint
            self.load_status, self.load_error = loaded.status, loaded.error
            self._apply_saved(loaded.settings)
            return True
        if answer == QMessageBox.StandardButton.Save:
            self.fingerprint = self.repository.load().fingerprint
            return self.save_settings()
        return False

    def _apply_saved(self, settings: Settings) -> None:
        theme_changed = settings.theme is not self.saved.theme
        self.saved = settings
        self.load_status = LoadStatus.LOADED
        self._load_form(settings)
        app = QApplication.instance()
        if theme_changed and isinstance(app, QApplication):
            apply_theme(app, settings.theme)
        self.retranslate()

    # ------------------------------------------------------------------ statistics
    def refresh_statistics(self) -> None:
        t = self.t
        if not self.saved.statistics_enabled:
            self.stats_view.setPlainText(t("stats.disabled"))
            return
        try:
            stats = self.stats_repo.load()
        except StatisticsError as exc:
            self.stats_view.setPlainText(t("summary.stats_error", error=exc.code))
            return
        lines = [f"{t('stats.documents')}: {stats.attempted}"]
        lines += [f"  {t(f'outcome.{o.value}')}: {stats.outcomes.get(o.value, 0)}" for o in Outcome]
        lines.append(f"{t('stats.pages')}:")
        lines += [f"  {key}: {value}" for key, value in sorted(stats.pages.items())]
        lines.append(f"{t('stats.languages')}:")
        lines += [f"  {t(f'lang.{k}')}: {v}" for k, v in sorted(stats.languages.items())]
        lines.append(t("stats.detected"))
        lines.append(f"{t('stats.timing')}:")
        doc = describe(stats.document_seconds)
        page = describe(stats.page_estimate_seconds)
        lines.append(
            "  "
            + t(
                "stats.per_document",
                count=doc.count,
                mean=doc.mean,
                median=doc.median,
                total=doc.total,
            )
            if doc
            else f"  {t('stats.unavailable')}"
        )
        lines.append(
            "  " + t("stats.per_page", mean=page.mean, median=page.median)
            if page
            else f"  {t('stats.unavailable')}"
        )
        self.stats_view.setPlainText("\n".join(lines))

    def reset_statistics(self) -> None:
        answer = self.message(
            QMessageBox.Icon.Question,
            APP_NAME,
            self.t("stats.reset_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.stats_repo.reset()
            except StatisticsError as exc:
                self.stats_view.setPlainText(self.t("summary.stats_error", error=exc.code))
                return
            self.refresh_statistics()

    # ------------------------------------------------------------------ launcher
    def install_launcher(self) -> None:
        command = launch_command(
            frozen=bool(getattr(sys, "frozen", False)),
            executable=sys.executable,
            appimage=os.environ.get("APPIMAGE"),
        )
        try:
            install_desktop_entry(default_data_home(os.environ), command)
        except OSError as exc:
            text = self.t("launcher.failed", error=exc)
            icon = QMessageBox.Icon.Warning
        else:
            text = self.t("launcher.installed")
            icon = QMessageBox.Icon.Information
        self.message(icon, APP_NAME, text, QMessageBox.StandardButton.Ok)

    # ------------------------------------------------------------------ window events
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        self.drop_zone.dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.drop_zone.dropEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        batch = self.batch
        if batch is not None:
            answer = self.message(
                QMessageBox.Icon.Question,
                APP_NAME,
                self.t("close.running"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            batch.cancel()
            batch.wait()
        if self.dirty:
            answer = self.message(
                QMessageBox.Icon.Question,
                self.t("close.title"),
                self.t("close.text"),
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel or (
                answer == QMessageBox.StandardButton.Save and not self.save_settings()
            ):
                event.ignore()
                return
        event.accept()


class FileOpenFilter(QObject):
    """Queues macOS Finder open/drop events (they may arrive after startup)."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FileOpen:
            path = event.file()  # type: ignore[attr-defined]
            if path:
                self.window.add_paths([Path(path)])
                if self.window.running:
                    self.window.autostart_pending = True  # start once the batch is done
                else:
                    self.window.start()
            return True
        return False
