# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
"""English/German message catalogs (VISION §6.3).

The processing core only emits reason codes and outcome names; this module turns them
into user-facing text. English is the default; German covers menus, settings, prompts,
errors, progress and summaries. Unknown keys fall back to English, then to the key.
"""

from __future__ import annotations

from searchify_pdf.domain.settings import UiLanguage

EN = UiLanguage.ENGLISH
DE = UiLanguage.GERMAN

MESSAGES: dict[str, dict[UiLanguage, str]] = {
    # --- outcomes -----------------------------------------------------------------------
    "outcome.converted": {EN: "Converted", DE: "Umgewandelt"},
    "outcome.preserved": {EN: "Copied (text kept)", DE: "Kopiert (Text beibehalten)"},
    "outcome.skipped": {EN: "Skipped", DE: "Übersprungen"},
    "outcome.failed": {EN: "Failed", DE: "Fehlgeschlagen"},
    "outcome.cancelled": {EN: "Cancelled", DE: "Abgebrochen"},
    "outcome.action_required": {EN: "Needs a decision", DE: "Entscheidung nötig"},
    # --- states -------------------------------------------------------------------------
    "state.discovered": {EN: "Found", DE: "Gefunden"},
    "state.deciding": {EN: "Checking", DE: "Prüfen"},
    "state.queued": {EN: "Waiting", DE: "Wartet"},
    "state.running": {EN: "Recognizing text…", DE: "Texterkennung läuft…"},
    "state.validating": {EN: "Checking result", DE: "Ergebnis wird geprüft"},
    "state.publishing": {EN: "Saving copy", DE: "Kopie wird gespeichert"},
    "state.finished": {EN: "Done", DE: "Fertig"},
    # --- reasons ------------------------------------------------------------------------
    "reason.ok": {EN: "Searchable copy created", DE: "Durchsuchbare Kopie erstellt"},
    "reason.output_exists": {
        EN: "A searchable copy already exists",
        DE: "Eine durchsuchbare Kopie existiert bereits",
    },
    "reason.user_skipped": {EN: "Skipped by you", DE: "Von Ihnen übersprungen"},
    "reason.generated_copy": {
        EN: "This is a copy made by Searchify PDF",
        DE: "Dies ist eine von Searchify PDF erstellte Kopie",
    },
    "reason.looks_generated": {
        EN: "Name ends like a searchable copy; select the file directly to process it",
        DE: "Name endet wie eine durchsuchbare Kopie; Datei direkt auswählen, um sie zu verarbeiten",
    },
    "reason.encrypted": {
        EN: "This kind of PDF encryption is not supported",
        DE: "Diese Art der PDF-Verschlüsselung wird nicht unterstützt",
    },
    "reason.password_required": {
        EN: "Needs a password: run it in the window or a terminal, or pass --password-file",
        DE: "Benötigt ein Passwort: im Fenster oder Terminal starten oder --password-file angeben",
    },
    "reason.wrong_password": {
        EN: "Wrong password",
        DE: "Falsches Passwort",
    },
    "reason.restricted": {
        EN: "PDF has usage restrictions (owner password); enable "
        "“Also process PDFs with usage restrictions” in Settings",
        DE: "PDF hat Nutzungsbeschränkungen (Besitzerpasswort); in den Einstellungen "
        "„Auch PDFs mit Nutzungsbeschränkungen verarbeiten“ aktivieren",
    },
    "reason.signed": {
        EN: "Digitally signed PDF; a copy would invalidate the signature",
        DE: "Digital signiertes PDF; eine Kopie würde die Signatur ungültig machen",
    },
    "reason.invalid_pdf": {EN: "Not a readable PDF", DE: "Kein lesbares PDF"},
    "reason.unreadable": {EN: "Cannot read this item", DE: "Element kann nicht gelesen werden"},
    "reason.not_found": {EN: "Not found", DE: "Nicht gefunden"},
    "reason.not_pdf": {EN: "Not a PDF file", DE: "Keine PDF-Datei"},
    "reason.symlink": {EN: "Symbolic link skipped", DE: "Symbolische Verknüpfung übersprungen"},
    "reason.destination_alias": {
        EN: "The copy would overwrite the original",
        DE: "Die Kopie würde das Original überschreiben",
    },
    "reason.destination_collision": {
        EN: "Another file would produce the same copy name",
        DE: "Eine andere Datei würde denselben Kopienamen ergeben",
    },
    "reason.destination_symlink": {
        EN: "The copy's location is a symbolic link",
        DE: "Der Speicherort der Kopie ist eine symbolische Verknüpfung",
    },
    "reason.locked": {
        EN: "Another Searchify PDF window is writing this copy",
        DE: "Ein anderes Searchify-PDF-Fenster schreibt diese Kopie",
    },
    "reason.engine_failed": {EN: "Text recognition failed", DE: "Texterkennung fehlgeschlagen"},
    "reason.engine_missing": {
        EN: "Text recognition engine or language data is missing",
        DE: "Texterkennung oder Sprachdaten fehlen",
    },
    "reason.timeout": {
        EN: "Took too long and was stopped",
        DE: "Dauerte zu lange und wurde gestoppt",
    },
    "reason.redo_unsupported": {
        EN: "Replacing the existing text failed; nothing was rasterized and the original is unchanged",
        DE: "Ersetzen des vorhandenen Textes fehlgeschlagen; nichts wurde gerastert, das Original ist unverändert",
    },
    "reason.validation_failed": {
        EN: "The result failed the quality check and was discarded",
        DE: "Das Ergebnis hat die Prüfung nicht bestanden und wurde verworfen",
    },
    "reason.write_failed": {
        EN: "Could not write the copy",
        DE: "Kopie konnte nicht geschrieben werden",
    },
    "reason.disk_full": {EN: "The disk is full", DE: "Der Datenträger ist voll"},
    "reason.permission_denied": {
        EN: "No permission to write here",
        DE: "Keine Schreibberechtigung an diesem Ort",
    },
    "reason.cancelled": {EN: "Cancelled", DE: "Abgebrochen"},
    "reason.ask_noninteractive": {
        EN: "Setting is 'Ask me' but no one can answer; choose an option explicitly",
        DE: "Einstellung ist „Nachfragen“, aber niemand kann antworten; Option ausdrücklich wählen",
    },
    "reason.all_pages_have_text": {
        EN: "Already searchable; copied without changes",
        DE: "Bereits durchsuchbar; unverändert kopiert",
    },
    "reason.deskew_disabled_for_redo": {
        EN: "Straightening was skipped because existing text was replaced",
        DE: "Begradigen wurde übersprungen, weil vorhandener Text ersetzt wurde",
    },
    # --- application/UI -----------------------------------------------------------------
    "app.tagline": {EN: "Make scanned PDFs searchable.", DE: "Gescannte PDFs durchsuchbar machen."},
    "tab.convert": {EN: "Convert", DE: "Umwandeln"},
    "tab.settings": {EN: "Settings", DE: "Einstellungen"},
    "tab.statistics": {EN: "Statistics", DE: "Statistik"},
    "tab.about": {EN: "About", DE: "Über"},
    "drop.hint": {
        EN: "Drop PDFs or folders here — or use the buttons below",
        DE: "PDFs oder Ordner hier ablegen — oder die Schaltflächen unten verwenden",
    },
    "drop.subhint": {
        EN: "Folders include all subfolders. Copies are saved next to each original.",
        DE: "Ordner schließen alle Unterordner ein. Kopien werden neben dem Original gespeichert.",
    },
    "button.add_files": {EN: "Add PDFs…", DE: "PDFs hinzufügen…"},
    "button.add_folder": {EN: "Add folder…", DE: "Ordner hinzufügen…"},
    "button.clear": {EN: "Clear list", DE: "Liste leeren"},
    "button.start": {EN: "Start", DE: "Starten"},
    "button.cancel": {EN: "Cancel", DE: "Abbrechen"},
    "button.open_folder": {EN: "Open folder", DE: "Ordner öffnen"},
    "button.save": {EN: "Save settings", DE: "Einstellungen speichern"},
    "button.revert": {EN: "Revert", DE: "Zurücksetzen"},
    "button.reset_stats": {EN: "Delete statistics", DE: "Statistik löschen"},
    "button.install_launcher": {EN: "Add to app menu", DE: "Zum Anwendungsmenü hinzufügen"},
    "column.file": {EN: "File", DE: "Datei"},
    "column.folder": {EN: "Folder", DE: "Ordner"},
    "column.status": {EN: "Status", DE: "Status"},
    "column.details": {EN: "Details", DE: "Details"},
    "dialog.pick_files": {EN: "Choose PDFs", DE: "PDFs auswählen"},
    "dialog.pick_folder": {EN: "Choose a folder", DE: "Ordner auswählen"},
    "progress.idle": {EN: "Ready.", DE: "Bereit."},
    "progress.running": {
        EN: "{done} of {total} done · {workers} at a time",
        DE: "{done} von {total} fertig · {workers} gleichzeitig",
    },
    "progress.cancelling": {EN: "Cancelling…", DE: "Wird abgebrochen…"},
    "summary.title": {EN: "Finished", DE: "Abgeschlossen"},
    "summary.line": {
        EN: "{converted} converted · {preserved} copied · {skipped} skipped · {failed} failed · {cancelled} cancelled · {action_required} need a decision",
        DE: "{converted} umgewandelt · {preserved} kopiert · {skipped} übersprungen · {failed} fehlgeschlagen · {cancelled} abgebrochen · {action_required} brauchen eine Entscheidung",
    },
    "summary.omitted": {
        EN: "{count} item(s) not processed",
        DE: "{count} Element(e) nicht verarbeitet",
    },
    "summary.time": {EN: "Time: {seconds:.1f} s", DE: "Dauer: {seconds:.1f} s"},
    "summary.nothing": {EN: "No PDFs found.", DE: "Keine PDFs gefunden."},
    "summary.queued": {
        EN: "{count} more item(s) added during the run are queued — press Start.",
        DE: "{count} weitere(s) Element(e) wurden während des Laufs hinzugefügt — Start drücken.",
    },
    "summary.stats_error": {
        EN: "Statistics could not be saved: {error}",
        DE: "Statistik konnte nicht gespeichert werden: {error}",
    },
    # --- prompts ------------------------------------------------------------------------
    "ask.output.title": {EN: "Copy already exists", DE: "Kopie existiert bereits"},
    "ask.output.text": {
        EN: "“{name}” already exists.\nReplace it with a new searchable copy?",
        DE: "„{name}“ existiert bereits.\nDurch eine neue durchsuchbare Kopie ersetzen?",
    },
    "ask.text.title": {EN: "PDF already contains text", DE: "PDF enthält bereits Text"},
    "ask.text.text": {
        EN: "“{name}” already has text on {text_pages} of {pages} page(s).\nReplace the existing recognized text? (No keeps it and only adds text to image-only pages.)",
        DE: "„{name}“ hat bereits Text auf {text_pages} von {pages} Seite(n).\nVorhandenen erkannten Text ersetzen? (Nein behält ihn und ergänzt nur Seiten ohne Text.)",
    },
    "ask.password.title": {EN: "Password required", DE: "Passwort erforderlich"},
    "ask.password.text": {
        EN: "“{name}” is password-protected.\nEnter its password to make a searchable copy. "
        "The copy is protected with the same password.",
        DE: "„{name}“ ist passwortgeschützt.\nPasswort eingeben, um eine durchsuchbare Kopie "
        "zu erstellen. Die Kopie wird mit demselben Passwort geschützt.",
    },
    "ask.password.retry": {
        EN: "Wrong password for “{name}”. Try again.",
        DE: "Falsches Passwort für „{name}“. Bitte erneut versuchen.",
    },
    "ask.password.prompt": {
        EN: "Password (empty: skip this PDF, Ctrl+D: cancel all): ",
        DE: "Passwort (leer: dieses PDF überspringen, Strg+D: alles abbrechen): ",
    },
    "ask.password.ok": {EN: "Unlock", DE: "Entsperren"},
    "ask.apply_all": {
        EN: "Apply to the rest of this batch",
        DE: "Für den Rest dieses Durchlaufs übernehmen",
    },
    "ask.yes_replace": {EN: "Replace", DE: "Ersetzen"},
    "ask.no_skip": {EN: "Skip", DE: "Überspringen"},
    "ask.no_keep": {EN: "Keep existing text", DE: "Vorhandenen Text behalten"},
    "ask.cancel_all": {EN: "Cancel all", DE: "Alles abbrechen"},
    "close.title": {EN: "Unsaved settings", DE: "Nicht gespeicherte Einstellungen"},
    "close.text": {
        EN: "You changed settings without saving. Save them before closing?",
        DE: "Sie haben Einstellungen geändert, ohne zu speichern. Vor dem Schließen speichern?",
    },
    "close.running": {
        EN: "Conversion is still running. Cancel it and quit?",
        DE: "Die Umwandlung läuft noch. Abbrechen und beenden?",
    },
    # --- settings -----------------------------------------------------------------------
    "settings.group.recognition": {EN: "Text recognition", DE: "Texterkennung"},
    "settings.group.files": {EN: "Files", DE: "Dateien"},
    "settings.group.performance": {EN: "Performance", DE: "Leistung"},
    "settings.group.appearance": {EN: "Appearance & privacy", DE: "Darstellung & Datenschutz"},
    "settings.languages": {EN: "Document languages", DE: "Dokumentsprachen"},
    "settings.languages.hint": {
        EN: "Languages the documents are written in (not the app language).",
        DE: "Sprachen, in denen die Dokumente geschrieben sind (nicht die App-Sprache).",
    },
    "lang.eng": {EN: "English", DE: "Englisch"},
    "lang.deu": {EN: "German", DE: "Deutsch"},
    "settings.deskew": {EN: "Straighten tilted pages", DE: "Schiefe Seiten begradigen"},
    "settings.rotate": {EN: "Fix upside-down or sideways pages", DE: "Gedrehte Seiten aufrichten"},
    "settings.existing_text": {
        EN: "If a PDF already has text",
        DE: "Wenn ein PDF bereits Text hat",
    },
    "policy.text.never_replace": {
        EN: "Keep existing text (only add missing text)",
        DE: "Vorhandenen Text behalten (nur fehlenden ergänzen)",
    },
    "policy.text.ask": {EN: "Ask me", DE: "Nachfragen"},
    "policy.text.always_replace": {
        EN: "Always replace existing OCR text",
        DE: "Vorhandenen OCR-Text immer ersetzen",
    },
    "settings.restricted": {
        EN: "Also process PDFs with usage restrictions (the copy keeps them)",
        DE: "Auch PDFs mit Nutzungsbeschränkungen verarbeiten (die Kopie behält sie)",
    },
    "settings.existing_output": {
        EN: "If the searchable copy already exists",
        DE: "Wenn die durchsuchbare Kopie schon existiert",
    },
    "policy.output.overwrite": {EN: "Overwrite", DE: "Überschreiben"},
    "policy.output.ask": {EN: "Ask me", DE: "Nachfragen"},
    "policy.output.never_overwrite": {
        EN: "Never overwrite (skip)",
        DE: "Nie überschreiben (überspringen)",
    },
    "settings.suffix": {EN: "Name ending for copies", DE: "Namensendung der Kopien"},
    "settings.suffix.example": {EN: "Example: {example}", DE: "Beispiel: {example}"},
    "settings.workers": {EN: "Documents at the same time", DE: "Dokumente gleichzeitig"},
    "workers.auto": {EN: "Automatic", DE: "Automatisch"},
    "workers.sequential": {EN: "One after another", DE: "Nacheinander"},
    "workers.fixed": {EN: "Fixed number", DE: "Feste Anzahl"},
    "settings.workers.auto_hint": {
        EN: "Automatic currently means {count} on this computer.",
        DE: "Automatisch bedeutet auf diesem Computer derzeit {count}.",
    },
    "settings.statistics": {
        EN: "Keep local usage statistics (never sent anywhere)",
        DE: "Lokale Nutzungsstatistik führen (wird nie versendet)",
    },
    "settings.theme": {EN: "Theme", DE: "Farbschema"},
    "theme.system": {EN: "Follow system", DE: "Wie System"},
    "theme.light": {EN: "Light", DE: "Hell"},
    "theme.dark": {EN: "Dark", DE: "Dunkel"},
    "settings.ui_language": {EN: "App language", DE: "App-Sprache"},
    "settings.file": {EN: "Settings file: {path}", DE: "Einstellungsdatei: {path}"},
    "settings.saved": {EN: "Settings saved.", DE: "Einstellungen gespeichert."},
    "settings.unsaved": {EN: "Unsaved changes", DE: "Ungespeicherte Änderungen"},
    "settings.invalid": {EN: "Invalid value: {detail}", DE: "Ungültiger Wert: {detail}"},
    "settings.malformed": {
        EN: "The settings file could not be read ({error}); defaults are in use. Saving keeps a backup of the old file.",
        DE: "Die Einstellungsdatei konnte nicht gelesen werden ({error}); Standardwerte sind aktiv. Beim Speichern wird eine Sicherung der alten Datei behalten.",
    },
    "settings.readonly": {
        EN: "Settings cannot be saved next to the app ({folder}). Move Searchify PDF to a folder you can write to, e.g. your home folder, and start it from there.",
        DE: "Einstellungen können nicht neben der App gespeichert werden ({folder}). Verschieben Sie Searchify PDF in einen beschreibbaren Ordner, z. B. Ihren Benutzerordner, und starten Sie es dort.",
    },
    "settings.save_failed": {
        EN: "Saving failed ({code}). Your changes are still here; the previous settings file is unchanged.",
        DE: "Speichern fehlgeschlagen ({code}). Ihre Änderungen sind noch da; die bisherige Einstellungsdatei ist unverändert.",
    },
    "settings.stale": {
        EN: "The settings file was changed by another window. Reload it (your changes are lost) or overwrite it with your changes?",
        DE: "Die Einstellungsdatei wurde von einem anderen Fenster geändert. Neu laden (Ihre Änderungen gehen verloren) oder mit Ihren Änderungen überschreiben?",
    },
    "settings.reload": {EN: "Reload", DE: "Neu laden"},
    "settings.overwrite": {EN: "Overwrite", DE: "Überschreiben"},
    # --- statistics ---------------------------------------------------------------------
    "stats.disabled": {
        EN: "Statistics are off. Turn them on in Settings to keep local counts and timings.",
        DE: "Statistik ist aus. In den Einstellungen einschalten, um lokale Zählungen und Zeiten zu führen.",
    },
    "stats.documents": {EN: "Documents", DE: "Dokumente"},
    "stats.pages": {EN: "Pages", DE: "Seiten"},
    "stats.timing": {EN: "Timing", DE: "Zeiten"},
    "stats.languages": {EN: "Configured languages", DE: "Eingestellte Sprachen"},
    "stats.detected": {
        EN: "Detected document language: not measured",
        DE: "Erkannte Dokumentsprache: nicht gemessen",
    },
    "stats.per_document": {
        EN: "Per document: {count} measured · mean {mean:.1f} s · median {median:.1f} s · total {total:.1f} s",
        DE: "Pro Dokument: {count} gemessen · Mittel {mean:.1f} s · Median {median:.1f} s · Summe {total:.1f} s",
    },
    "stats.per_page": {
        EN: "Per page (estimate: document time ÷ OCR pages, not measured): mean {mean:.2f} s · median {median:.2f} s",
        DE: "Pro Seite (Schätzung: Dokumentzeit ÷ OCR-Seiten, nicht gemessen): Mittel {mean:.2f} s · Median {median:.2f} s",
    },
    "stats.unavailable": {EN: "unavailable", DE: "nicht verfügbar"},
    "stats.reset_confirm": {
        EN: "Delete all local statistics?",
        DE: "Alle lokalen Statistiken löschen?",
    },
    # --- about --------------------------------------------------------------------------
    "about.text": {
        EN: "Searchify PDF {version}\nOCR runs locally on this computer; documents are never uploaded.\nLicense: GPL-3.0-or-later.",
        DE: "Searchify PDF {version}\nDie Texterkennung läuft lokal auf diesem Computer; Dokumente werden nie hochgeladen.\nLizenz: GPL-3.0-or-later.",
    },
    "about.components": {
        EN: "Bundled components and licenses",
        DE: "Enthaltene Komponenten und Lizenzen",
    },
    "about.engine": {EN: "Engine: {engine}", DE: "Engine: {engine}"},
    "launcher.installed": {
        EN: "Added to the app menu. You can now drop PDFs or folders onto the Searchify PDF launcher.",
        DE: "Zum Anwendungsmenü hinzugefügt. Sie können jetzt PDFs oder Ordner auf den Searchify-PDF-Starter ziehen.",
    },
    "launcher.failed": {
        EN: "Could not add launcher: {error}",
        DE: "Starter konnte nicht hinzugefügt werden: {error}",
    },
}


def tr(key: str, language: UiLanguage = EN, /, **values: object) -> str:
    """Translate ``key`` and format it with ``values``."""
    entry = MESSAGES.get(key)
    text = key if entry is None else entry.get(language) or entry[EN]
    return text.format(**values) if values else text
