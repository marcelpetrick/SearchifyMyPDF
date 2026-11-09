# 0006 — Bundled language data

- Status: accepted
- Date: 2026-11-09

## Decision
Bundle `tessdata_fast` 4.1.0 `eng`, `deu` and `osd` (Apache-2.0), downloaded by
`scripts/fetch_tessdata.sh` and verified by SHA-256. Default OCR languages: `eng+deu`.
UI language and OCR languages are independent settings. The settings model accepts any
Tesseract language code; the UI offers the bundled ones. No automatic language detection
(statistics report detected language as "not measured").

## Consequences
Small download (~16 MB of data) with decent speed; `tessdata_best` or more languages are a
deferred backlog item.
