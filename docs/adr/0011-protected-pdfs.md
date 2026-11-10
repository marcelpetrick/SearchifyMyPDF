# 0011 — Password-protected and owner-restricted PDFs

- Status: accepted (owner decision on #12, 2026-11-10)
- Date: 2026-11-10

## Context
VISION §4.3 asked for protected inputs to be rejected in the MVP and never to bypass
protection. Real archives contain two kinds of encrypted PDFs:

- **open password** (user password): the PDF cannot be opened without it;
- **owner restrictions** only: it opens without a password but forbids e.g. copying text
  or editing (the NDL scan in `tests/fixtures/real`).

The owner decided to support both, without weakening the protection of the copy.

## Decision
- **Open password:** the user is asked (window dialog with hidden input; terminal prompt
  with hidden input; `--password-file` with one password per line for headless/Docker
  runs). Up to three attempts; *Skip* and *Cancel all* are offered. A password that worked
  is tried first on the rest of the batch, so a folder of statements asks once.
  Without a way to ask, the document fails with `password_required`.
- **Owner restrictions:** rejected with `restricted` unless the setting *Also process PDFs
  with usage restrictions* (`process_restricted_pdfs`, CLI `--process-restricted`) is on.
- **The copy is protected like the source:** same open password, same permission flags,
  always AES-256 (R6). The owner password is the source's when the user entered it;
  otherwise it is unknown and a random one is set, so the restrictions cannot be lifted
  from the copy either. Blank-owner-password encryption (no real restriction) is handled
  like an open PDF that is re-encrypted the same way.
- **No decrypted data beside the original:** the source is decrypted into a private
  `0700` temporary folder for the engine, the OCR output is validated and stamped there,
  then encrypted into the staging file and published as usual (ADR 0004). The folder is
  removed in every outcome. Passwords live only in memory: never in settings, statistics,
  logs, command lines (the engine worker gets file paths only) or summaries.
- **Digitally signed PDFs stay rejected** (a copy would invalidate the signature), also
  when they are encrypted. Unsupported encryption (e.g. certificate security handlers)
  stays `encrypted`.

## Consequences
- VISION §4.3 updated accordingly.
- Tests: unit (`tests/unit/test_protected_pdfs.py`: inspection, re-encryption, prompts,
  retries, reuse, skip/cancel, private work folder cleanup, CLI), integration with real OCR
  (password scan, the real NDL restricted scan keeps its exact permission flags), UI
  (password dialog path, setting), packaged E2E and Docker-image E2E with `--password-file`.
- Desktop search tools may not index text of password-protected copies; that is inherent
  to keeping them protected.
