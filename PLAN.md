# PLAN.md — implementation plan for Searchify PDF

Derived from [`VISION.md`](VISION.md). Requirement IDs (A01–A20) refer to VISION §15.
Status legend: ✅ done · 🟡 partial / limited evidence · ⏳ deferred (tracked as issue) · ❌ open.

## Decisions taken up front (details in `docs/adr/`)

| Topic | Decision | ADR |
| --- | --- | --- |
| Python baseline | 3.12 (still supported on Windows 10; tested on 3.12 + 3.13) | 0001 |
| GUI toolkit | PySide6-Essentials (LGPL-3.0, Qt Widgets, offscreen-testable) | 0001 |
| Bundler | PyInstaller one-file Linux executable built in an Ubuntu 22.04 container (glibc 2.35 baseline) bundling Tesseract, its libraries and eng/deu/osd data | 0002 |
| Process strategy | One engine **subprocess** per document (own session/process group) so cancel can kill the whole tree; shared CPU budget | 0003 |
| Output atomicity | Stage in destination dir → validate → `os.replace` (overwrite) or `os.link` no-clobber with lock-guarded rename fallback | 0004 |
| Native drop | Linux `.desktop` launcher (`Exec=… %F`, PDF + folder MIME types); window drag & drop; file/folder pickers as fallback | 0005 |
| Language data | tessdata_fast 4.1.0 eng + deu + osd, pinned by SHA-256 | 0006 |
| Licensing | Project GPL-3.0-or-later; component inventory generated at build | 0007 |
| Settings/statistics storage | Versioned JSON beside the app (`searchify-pdf.settings.json`, `searchify-pdf.statistics.json`) | 0008 |
| Generated-file detection & override | Suffix (current + previous) + PDF metadata marker | 0009 |

## Milestones

### M0 — preparation
1. Repo scaffold, GPLv3, AGENTS/PLAN, version + changelog tooling.
2. `localPipeline.sh` (format, lint, types, tests, coverage, build, packaged E2E, Docker).
3. GitHub Actions mirroring the pipeline.

### M1 — Linux vertical slice (MVP)
4. Domain: settings model + validation, policies, path mapping, outcomes/events.
5. Storage: portable settings repository (atomic, versioned, migrations, stale detection).
6. Discovery: recursive, symlink rules, generated-copy exclusion, collisions.
7. PDF inspection: page text, encryption, signatures.
8. Engine interface + OCRmyPDF adapter in subprocess worker.
9. Publisher: staging, validation, locks, overwrite/no-clobber.
10. Scheduler: auto/sequential/fixed, cancellation, timeouts.
11. Workflow: settings snapshot, policy decisions, prompts, summary.
12. CLI (non-interactive Ask handling, exit codes).
13. Qt UI: convert view, settings, save/close, progress, cancel, about/licenses.
14. Packaging: PyInstaller binary with bundled Tesseract; packaged E2E in a clean container.
15. Release workflow: tested artifact, checksums, inventory, draft prerelease.

### M2 — Linux hardening
16. i18n English/German, light/dark themes, accessibility basics.
17. Optional statistics (off by default, medians, reset).
18. Fault/adversarial tests, red-team review notes (`docs/security-review.md`).
19. Mutation testing baseline (`docs/mutation-baseline.md`) + scheduled workflow.
20. Docker image (CLI) published to GHCR.

### M2b — Test depth and a smaller executable (requested 2026-11-10)
Goal: prove more behaviour **on the shipped artifacts**, then shrink the Linux executable
drastically **without losing any functionality** (all E2E tests stay green unchanged).

Baseline (0.16.14): `searchify-pdf-0.16.14-linux-x86_64` = **133.6 MB** (788 entries,
326 MB unpacked). Largest avoidable parts, measured with the PyInstaller archive reader:
two ICU data copies (Qt ICU 73: 12.3 MB; Ubuntu ICU 70: 11.7 MB, pulled only by
Tesseract → libarchive → libxml2), dev tools leaking into the bundle (hypothesis,
mypy's `ast_serialize`, setuptools), unused optional codecs (Pillow AVIF), unstripped
native libraries (−20 MB unpacked). PyInstaller only supports zlib; xz would give
~96 MB but needs a self-extracting wrapper or AppImage/FUSE → rejected (UX, FUSE missing
on stock Ubuntu 22.04+).

Test data and E2E (first, so they guard the size work):
21. **Fixtures:** more real-life public-domain / CC scans (different eras, layouts and
    languages incl. German) with provenance in `tests/fixtures/real/SOURCES.md`; more
    synthetic variants (skew, noise, low resolution, landscape, two columns, long
    documents) in `tests/synthetic.py` and `scripts/generate_samples.py`.
22. **Packaged E2E:** the binary converts the real-life corpus (expected words found);
    `docker stop` cancels a packaged run cleanly (exit 1, no leftovers); interactive
    terminal prompts (replace/skip/apply-to-all) through a pseudo-terminal.
23. **Docker image E2E:** the same scenarios against the published image (corpus,
    `/config` settings, `docker stop` cancel, non-root, offline).
24. **Desktop launcher E2E:** install the desktop entry and launch it through
    `gio launch` with files on a real X server (Xvfb) — exercises the `%F` path a file
    manager uses. A physical drag in GNOME/KDE stays a manual check (#7).

Size reduction (each step measured; E2E must pass before commit). Target: ≤ 100 MB
(−25 %); Qt, Python, OCRmyPDF and Tesseract themselves are the irreducible core.
25. Build environment with runtime dependencies + PyInstaller only (no dev group).
26. Strip native libraries; exclude unused optional modules (Pillow AVIF, unused Qt
    image formats / plugins) — only where tests prove the feature is unaffected.
27. Bundle a Tesseract built from source without libarchive/curl/training tools
    (drops libarchive, libxml2, ICU 70 …); inventory lists it as a source-built component.
    Risk: Tesseract 4.1.1 → 5.x changes recognition slightly; the word checks on the
    real-life corpus guard it. Cost: a few minutes more for an uncached builder image.
28. Optional if still needed: a Qt ICU 73 data library trimmed to the locales the UI uses.
29. Size budget gate (`scripts/check_binary_size.py`) in the pipeline so it cannot regress;
    record before/after in `docs/benchmarks.md`.

**M2b result (0.17.3):** steps 21–29 done. 133.6 MB → **90.8 MB (−32 %)**, unpacked
326 → 210 MB, same functionality (all packaged E2E green after every step; GUI also
checked on a real Wayland session). Real-life corpus of 6 documents (1929–1967, EN/DE,
PD + CC BY-SA), 8 scanner-defect variants, 8 packaged + 4 Docker-image E2E tests. Found and
fixed on the way: invalid desktop entry (`Version=1.5`, two main categories).

30. ✅ **Protected PDFs (#12, owner chose both a and b, ADR 0011):** (a) open-password
    PDFs: password dialog / hidden terminal prompt / `--password-file`, copy protected
    with the same password and permissions; (b) owner-restricted PDFs: opt-in setting
    `process_restricted_pdfs` / `--process-restricted`, copy keeps the restrictions.
    Decrypted data only in a private temp folder; signed PDFs stay rejected.
31. ✅ **Recognition quality gate (requested 2026-11-10):** full ground truth instead of
    keywords — synthetic English/German pages (DejaVu fonts with ä ö ü ß, 3 resolutions,
    4 scanner defects) and the real 1950 page vs. its published text layer; on the dev
    setup, the packaged executable and the Docker image. Found and fixed: `eng+deu`
    dropped umlauts (92.7 % → 100 % German words) — the engine now passes English last.
    Results: [`docs/benchmarks.md`](docs/benchmarks.md#recognition-quality-plan-step-31).
32. ⏳ **Public release with Linux, Windows and macOS (requested 2026-11-10):** native
    Windows/macOS builds with smoke tests (`native.yml`), release workflow publishes a
    public release with all three platforms and verifies the published assets.

### M3 / M4 — Windows, macOS
Architecture keeps platform adapters separate; artifacts and native evidence are
**not** produced yet (no claims of support). Tracked as deferred issues.

## Status

Architecture: [`docs/architecture.md`](docs/architecture.md) (C4 context/container/component,
flowcharts, sequence diagrams and the GitHub Actions pipeline in Mermaid) and
[`docs/adr/`](docs/adr/). Working rules: [`AGENTS.md`](AGENTS.md).

Milestones: **M0 ✅ · M1 ✅ · M2 ✅ (Linux prerelease pending owner review of the draft) ·
M2b ✅ (steps 21–30) · M3 ⏳ #10 · M4 ⏳ #11.** Deferred backlog: issues #2–#9, #12, #13.

| ID | Status | Evidence |
| --- | --- | --- |
| A01 | ✅ | `tests/integration/test_real_corpus.py` (real PD/CC scans 1929–1967, EN/DE), `test_engine_ocr.py` (synthetic EN/DE, 8 scanner defects), packaged + Docker-image E2E on the real corpus |
| A02 | ✅ | checksums before/after in workflow, fault (kill, cancel, overwrite failure) and E2E tests |
| A03 | ✅ | `test_folder_recursive_adjacent_and_repeat_run`, `test_nested_unicode_folder_real_ocr`, E2E offline conversion |
| A04 | ✅ | repeat-run, suffix-change and explicit-override tests (`test_workflow.py`, `test_inspect_discovery.py`) |
| A05 | ✅ | keep/ask/replace with digital and mixed fixtures; redo never force-rasterizes (`test_redo_replaces_previous_ocr_without_rasterizing`) |
| A06 | ✅ | overwrite/ask/skip incl. failed replacement keeps previous copy; CLI exit code 3 |
| A07 | ✅ | UI save/close/discard/cancel, write failure, read-only, malformed, stale settings tests |
| A08 | ✅ | packaged E2E: settings beside the executable, read-only app folder, no other writes |
| A09 | 🟡 | packaged E2E: installed launcher validated and started via `gio launch` with dropped files on a real X server, window mapped, files converted; GUI smoke on a real Wayland session; physical drag in GNOME/KDE: manual check pending (#7) |
| A10 | ✅ | packaged E2E in clean, offline Ubuntu 22.04 containers without Python/Tesseract |
| A11 | 🟡 | light/dark + EN/DE tested offscreen, screenshots in README; formal accessibility review pending (#7) |
| A12 | ✅ | worker-limit test (max concurrency), cancellation kills process tree, timeout test, benchmark |
| A13 | ✅ | off by default, true medians, no double counting, failure handling (`test_statistics.py`) |
| A14 | ✅ | locks, simultaneous instances, no-clobber, disk full, permission, alias, hard-kill recovery |
| A15 | ✅ | 100 % statement / 100 % branch (minimum 95 % each, enforced separately) |
| A16 | ✅ | mutation 100 % of non-equivalent (min 95 %), real-OCR integration, packaged E2E |
| A17 | ✅ | `docs/desktop-matrix.md` advertises Linux x86-64 only |
| A18 | 🟡 | release workflow promotes tested assets with SHA256SUMS + inventory to a **draft**; owner reviews/publishes (#12) |
| A19 | ⏳ | procedure in `docs/windows-search.md`; Windows build is M3 (#10) |
| A20 | ✅ | `docs/security-review.md` with regression tests; residual risk #13 |

## Progress log (one row per commit, appended by `scripts/commit.sh`)

| Version | Date | Step |
| --- | --- | --- |
| 0.1.0 | 2026-11-09 | chore: scaffold project with GPLv3, tooling and local pipeline |
| 0.1.1 | 2026-11-09 | ci: run localPipeline.sh in GitHub Actions on Python 3.12 and 3.13 |
| 0.1.2 | 2026-11-09 | chore: log every commit step in PLAN.md via commit helper |
| 0.2.0 | 2026-11-09 | feat(domain): add validated settings, policies, path rules and job outcomes |
| 0.3.0 | 2026-11-09 | feat(storage): add portable settings repository, atomic writes and stale-safe locks |
| 0.4.0 | 2026-11-09 | feat(discovery): add PDF inspection and recursive discovery with generated-copy exclusion |
| 0.5.0 | 2026-11-09 | feat(engine): add OCRmyPDF adapter running isolated, cancellable worker processes |
| 0.6.0 | 2026-11-09 | feat(publisher): add validated staging publication and shared CPU budget scheduler |
| 0.7.0 | 2026-11-09 | feat(workflow): add batch workflow with policy decisions, prompts, locking and cancellation |
| 0.8.0 | 2026-11-09 | feat(i18n): add English and German catalogs for outcomes, reasons, UI and prompts |
| 0.9.0 | 2026-11-09 | feat(statistics): add opt-in local statistics with true medians and labelled estimates |
| 0.10.0 | 2026-11-09 | feat(platform): add bundled runtime setup, Linux launcher integration and component inventory |
| 0.11.0 | 2026-11-09 | feat(ui): add Qt desktop UI with drop zone, progress, prompts, settings, statistics and about |
| 0.12.0 | 2026-11-09 | feat(cli): add entry point with drop-launch dispatch, headless CLI and exit codes |
| 0.12.1 | 2026-11-09 | fix(engine): run OCRmyPDF page workers as threads for frozen-app safety |
| 0.13.0 | 2026-11-10 | build(linux): add self-contained PyInstaller executable with bundled Tesseract and packaged E2E tests |
| 0.14.0 | 2026-11-10 | ci(release): add tag-triggered release pipeline promoting tested assets to a draft release |
| 0.15.0 | 2026-11-10 | build(docker): add headless CLI image with smoke test and GHCR publishing workflow |
| 0.16.0 | 2026-11-10 | test(mutation): add mutmut baseline, hardening tests, threshold and scheduled workflow |
| 0.16.1 | 2026-11-10 | fix(publisher): remove staging leftovers of interrupted runs and add fault tests |
| 0.16.2 | 2026-11-10 | fix(ui): improve progress bar contrast and escape ampersand in group titles |
| 0.16.3 | 2026-11-10 | fix(inventory): list only bundled runtime components and the PyInstaller bootloader |
| 0.16.4 | 2026-11-10 | docs(architecture): add C4 views, flow diagrams, pipeline overview and ADRs 0001-0009 |
| 0.16.5 | 2026-11-10 | docs: add security review, compliance checklist, desktop matrix, Windows Search guide and benchmark baseline |
| 0.16.6 | 2026-11-10 | ci(deps): add Dependabot and daily pip-audit dependency scan |
| 0.16.7 | 2026-11-10 | docs(readme): document usage, pipeline, Docker and add real UI screenshots |
| 0.16.8 | 2026-11-10 | chore(scripts): add sample corpus generator and run mutation checks on core PRs |
| 0.16.9 | 2026-11-10 | docs(plan): record milestone status and evidence for A01-A20 |
| 0.16.10 | 2026-11-10 | fix(ui): keep paths added during a run queued and start open events afterwards |
| 0.16.11 | 2026-11-10 | fix(ui): record statistics according to the batch settings snapshot |
| 0.16.12 | 2026-11-10 | fix(cli): cancel headless runs cleanly on SIGINT and SIGTERM |
| 0.16.13 | 2026-11-10 | fix(storage): never break a live same-host lock and age out foreign locks after the max timeout |
| 0.16.14 | 2026-11-10 | test(storage): cover staging leftovers that cannot be deleted |
| 0.16.15 | 2026-11-10 | docs(plan): plan more E2E coverage, real-life fixtures and a smaller executable |
| 0.16.16 | 2026-11-10 | test(fixtures): add real-life public-domain and CC BY-SA scan corpus with workflow tests |
| 0.16.17 | 2026-11-10 | test(fixtures): generate scanner-defect, long and owner-restricted synthetic PDFs with OCR tests |
| 0.16.18 | 2026-11-10 | test(e2e): packaged binary converts the real-life corpus, cancels on docker stop and prompts on a terminal |
| 0.16.19 | 2026-11-10 | test(e2e): run real-life corpus, /config settings, docker stop and non-root checks against the Docker image |
| 0.16.20 | 2026-11-10 | fix(desktop): write a launcher that desktop-file-validate accepts and lists once in menus |
| 0.16.21 | 2026-11-10 | test(e2e): launch the installed desktop entry with dropped files on a real X server |
| 0.16.22 | 2026-11-10 | build(linux): bundle only runtime dependencies and PyInstaller into the executable |
| 0.17.0 | 2026-11-10 | build(linux): bundle Tesseract 5.5.3 built from source without libarchive, ICU 70 and OpenMP |
| 0.17.1 | 2026-11-10 | build(linux): strip native libraries and drop unused codecs and Qt plugins |
| 0.17.2 | 2026-11-10 | build(linux): bundle Qt's ICU 73.2 data trimmed to the English/German UI |
| 0.17.3 | 2026-11-10 | ci(size): fail the pipeline above a 95 MB executable budget and document the size reduction |
| 0.17.4 | 2026-11-10 | docs(plan): record M2b results and the protected-PDF decision |
| 0.17.5 | 2026-11-10 | ci(docker): install Qt runtime libraries before running the image E2E tests |
| 0.17.6 | 2026-11-10 | build(linux): retry flaky mirror downloads when building the builder image |
| 0.17.7 | 2026-11-10 | ci(native): build and smoke-test Windows and macOS executables on GitHub runners |
| 0.17.8 | 2026-11-10 | ci(native): build the macOS executable on the macos-15 runner (macos-14 was retired) |
| 0.18.0 | 2026-11-10 | feat(protection): process password-protected and opt-in owner-restricted PDFs, copies stay protected |
| 0.18.1 | 2026-11-10 | fix(ocr): keep German umlauts by passing English last, gated by a ground-truth quality test |
