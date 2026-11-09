# 0008 — Portable settings and statistics files

- Status: accepted
- Date: 2026-11-09

## Decision
- `searchify-pdf.settings.json` beside the application (schema version 2, migrations from
  v1, strict validation, unknown keys ignored, 256 KiB limit). Atomic writes; a
  fingerprint taken at load time detects concurrent edits; a malformed file is kept as
  `*.invalid.bak` on the next save. **No** user-profile fallback; a read-only location
  produces guidance to move the app.
- `searchify-pdf.statistics.json` beside the application, only when enabled. Raw samples
  (≤ 100 000) for true medians, batch ids against double counting, no paths or text.
- `SEARCHIFY_PDF_HOME` overrides the location (tests, Docker `/config`).
