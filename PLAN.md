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

### M3 / M4 — Windows, macOS
Architecture keeps platform adapters separate; artifacts and native evidence are
**not** produced yet (no claims of support). Tracked as deferred issues.

## Status

Updated at the end of the work session; see the evidence matrix below.

| ID | Status | Evidence |
| --- | --- | --- |
| A01 | ❌ | |
| A02 | ❌ | |
| A03 | ❌ | |
| A04 | ❌ | |
| A05 | ❌ | |
| A06 | ❌ | |
| A07 | ❌ | |
| A08 | ❌ | |
| A09 | ❌ | |
| A10 | ❌ | |
| A11 | ❌ | |
| A12 | ❌ | |
| A13 | ❌ | |
| A14 | ❌ | |
| A15 | ❌ | |
| A16 | ❌ | |
| A17 | ❌ | |
| A18 | ❌ | |
| A19 | ❌ | |
| A20 | ❌ | |

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
