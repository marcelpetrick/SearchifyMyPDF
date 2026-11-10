# 0013 — Existing-text quality cross-check

- Status: accepted (issue #6; VISION §4.1/§14: meaningful signals and user review,
  text presence is not quality)
- Date: 2026-11-10

## Context
The three-way existing-text policy (keep / replace / ask) works without a quality score,
but "Ask me" left the user to guess whether an earlier OCR layer is any good. Typical
real cases: a scanner's built-in OCR from decades ago, a copy OCR'd in the wrong
language, or a born-digital PDF whose text is fine.

## Decision
- **Signal: agreement with a fresh recognition.** Up to three pages that carry text
  (first, middle, last) are rendered at 200 dpi — the invisible OCR layer is not drawn,
  visible text is — recognized with the configured languages, and compared with the
  page's existing text: Dice coefficient of the case-folded word multisets
  (`domain/text_quality.py`). Word order is ignored, so different column order is not
  an error; garbled, missing or invented words are.
- **Verdict:** good ≥ 85 %, poor < 50 %, doubtful in between, *unknown* when the fresh
  recognition finds fewer than 5 words or anything fails (no Tesseract, timeout,
  damaged page). Never a guess.
- **Where it is used (user review, not automatism):**
  - "Ask me": the check runs before the question, and the GUI/terminal prompt shows the
    result ("agrees on only 31 % of the words: it looks poor, replacing it is
    recommended"). The decision stays with the user. Kept doubtful/poor text leaves a
    note on the result. Skipped when the batch answer is already "replace all".
  - `--check-text PATHS`: a read-only report per PDF; writes nothing.
  - Setting *Before asking about existing text, compare up to 3 pages…*
    (`cross_check_existing_text`, default on; CLI `--cross-check/--no-cross-check`).
  - Not run for "Keep" or "Replace": those policies need no decision, and checking every
    born-digital PDF would cost seconds per file.
- The source is only read; renderings are written to a private (0700) temporary folder
  that is always removed. Password-protected sources are opened with the password the
  batch already has. Each Tesseract is single-threaded and the sampled pages run in
  parallel (OpenMP oversubscription made a dense page 2.6× slower).
- The engine provides the checker (`OcrEngine.text_checker`), so another engine can
  bring its own.

## Consequences
- Measured (docs/benchmarks.md "Existing-text cross-check"): correct OCR layers and
  born-digital text 100 %, a third of the lines garbled 63 % (doubtful), a fully garbled
  layer 0 % (poor), the real 1950 Bundesgesetzblatt publisher layer 86 % (good).
- Integration tests run the real Tesseract on synthetic OCR layers (correct, partly and
  fully garbled), a password-protected source, failures, the "Ask me" workflow and
  `--check-text`.
