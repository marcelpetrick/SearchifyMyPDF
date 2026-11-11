# Searchify PDF — Vision and Implementation Brief

**Working title:** Searchify PDF  
**Tagline:** Make scanned PDFs searchable.  
**Updated:** 9 November 2026  
**Status:** Consolidated product decisions and implementation guidance; not a claim of completed software.  
**Audience:** Developers and implementation agents preparing a GitHub project, automated tests, packaged applications, and public releases.

## 1. Authority and purpose

This document supersedes earlier drafts and preliminary prototype behavior wherever they conflict. It collects the user's decisions, explains the intended architecture, and defines evidence required before claiming support. This handoff does not authorize publishing a repository, choosing a license for the owner, purchasing infrastructure, or releasing unreviewed binaries. Those actions belong to the later implementation/release workflow.

Build a local desktop application that makes scanned PDFs searchable by embedding recognized text in copies of the documents. The audience is ordinary computer users who should not need Python, command-line knowledge, or a separate OCR installation.

The primary interaction is dropping a PDF or folder onto the application or its supported shortcut. It processes using saved settings. Opening the application normally displays its UI and settings. OCR is local; document contents are not uploaded.

The immediate goal is a working Linux MVP. Windows follows, then macOS. Monetization is a possible later direction, not a prerequisite or an MVP feature. No account, subscription, activation server, or payment system is required.

### Decision labels

- **Required:** explicitly decided behavior or necessary acceptance condition.
- **Proposed default:** a practical starting point where the user did not fix the exact value. Record changes in an architecture decision record (ADR).
- **Deferred:** capture as a future issue; do not let it block the MVP.
- **Open:** resolve at the stated milestone rather than silently inventing a requirement.

## 2. Settled product decisions

| Topic | Decision |
| --- | --- |
| Identity | Searchify PDF is the working title; use `searchify_pdf` as the Python package and `searchify-pdf` as the CLI identifier |
| Implementation | Python, with modular adapters so additional engines can be introduced later |
| Initial engine | OCRmyPDF orchestrates PDF conversion; Tesseract performs recognition |
| Users | Nontechnical users; plain language, clear outcomes, few required choices |
| Input | One PDF or a folder; folder processing includes all subfolders recursively |
| Output location | Each copy is placed beside its original, including throughout nested folders |
| Output name | Add a recognizable suffix; proposed default `_searchable.pdf` |
| Originals | Never modify or overwrite originals |
| Folder layout | No `output` or `ocr_output` directory is created for normal processing |
| Drop launch | Start processing immediately using current saved settings |
| Ordinary launch | Open a desktop UI with settings and file/folder selection |
| Persistence | Readable settings file beside the application so settings can travel with it |
| Distribution | Self-contained application per OS/architecture, with dependencies bundled |
| Platforms | Linux x86-64 first; Windows 10/11 second; macOS Intel and Apple Silicon third |
| UI | Colorful, polished, responsive, light/dark modes; English default and switchable German |
| OCR languages | English and German first; design for additional languages/scripts |
| Existing text | Preserve by default; support Always replace, Ask, and Never replace policies for existing OCR |
| Existing output | Support Overwrite, Ask, and Never overwrite; do not silently assume every existing output should be skipped |
| Parallelism | Auto, sequential, or a user-selected fixed number of concurrent documents |
| Statistics | Optional, persisted locally, disabled by default; counts, language information, and timing including medians |
| Quality | Black, Ruff, type checking, high statement/branch coverage, end-to-end and mutation tests |
| Release path | GitHub project, Actions pipelines, versioned public release assets after gates pass |
| Later | Updater, monetization, expanded engines/languages, broader tester recruitment |

## 3. Core user journeys

### 3.1 Drop a PDF

1. Receive the path through the OS launch/open mechanism.
2. Load saved settings; use documented defaults if no settings file exists.
3. Validate input, output path, permissions, and engine readiness.
4. Apply existing-text and existing-output policies where relevant.
5. Create a temporary result; validate it before publishing the copy.
6. Show progress and a persistent completion/error summary with an Open folder action.

Owner decision (2026-11-11, ADR 0015): a drop on the app/launcher works in the background by default: no window, only the questions the settings ask for, and a message only if something needs attention. The setting *Show this window when PDFs or folders are dropped* restores the window with progress and summary. Starting the app without files (double-click) always opens the window.

Example: `Contracts/Acme.pdf` becomes `Contracts/Acme_searchable.pdf`.

### 3.2 Drop a folder

Discover eligible PDFs recursively. A file at `Contracts/2025/Acme.pdf` becomes `Contracts/2025/Acme_searchable.pdf`. No additional output tree is introduced. Preserve each original's filename stem and directory, applying the configured suffix only to the copy.

Snapshot eligible inputs before workers start. Exclude generated copies so a run does not consume its own output or produce repeated `_searchable_searchable` names. When an original has an existing generated copy, process the original according to the output-conflict policy; exclusion of generated files must not mean excluding their originals.

Proposed discovery rules: case-insensitive `.pdf` extension; no directory symlink traversal; skip symlink files during folder discovery; normalize/deduplicate paths and detect output collisions before writing. Test long paths, spaces, Unicode, case-only differences, unreadable subfolders, and duplicate launch paths. Report omissions rather than silently dropping errors.

For generated-file identification, persist/recognize the active suffix and prior configured suffixes, and use an application metadata marker where feasible. A naturally named source ending in the suffix must be reported as excluded and remain processable by an explicit user action. Decide and document that override before release.

### 3.3 Open without input

Display the main UI, not a terminal error. Provide file/folder selection, Start, progress/results, settings, About/Licenses, and optional statistics. Support keyboard navigation and readable status messages. Dragging into the open window is useful but distinct from dropping on the application icon; add it without confusing the two mechanisms.

Multiple OS-delivered files should be queued and deduplicated. Native launch/open events may arrive after startup, particularly on macOS. Do not build the application around the assumption that every platform supplies only `argv[1]` at process creation.

### 3.4 Repeated runs and cancellation

Every job uses an immutable settings snapshot. UI edits affect subsequent jobs only. Continue after an individual document fails, reporting converted, preserved/copied, skipped, failed, and cancelled outcomes separately. Cancel should stop queued jobs and terminate active child processes cleanly; retain already completed outputs and discard incomplete temporary results.

Multiple app instances must not race to replace the same output. Use an explicit per-target coordination strategy with stale-lock recovery, and serialize prompts appropriately. Do not infer safety from a file-existence check alone.

## 4. Two separate replacement policies

### 4.1 Existing recognized text

User-facing choices: **Always replace existing OCR**, **Ask me**, **Never replace existing OCR**. Default: Never replace existing OCR / preserve existing text.

These govern the generated copy, never editing the source. Preserve born-digital text and vector content. When replacement is requested, use the engine's redo-OCR capability where supported to replace the old invisible layer. Do not silently substitute force-rasterization: it can alter visible/vector content and reduce quality. If safe redo is unsupported or fails, report the limitation or ask explicitly about an advanced action.

For mixed PDFs, make the policy page-aware. Preserving existing text must still allow image-only pages to receive OCR. Pages containing both digital text and scanned regions require careful engine handling; document limitations rather than claiming a blanket skip-text mode recognizes every image region.

A “cross-check OCR quality” function is deferred unless needed to implement the policy accurately. Presence of text does not prove its quality. The three-way policy is required even without an automated quality score. Decision (issue #6, ADR 0013): “Ask me” first compares up to three pages with a fresh recognition and shows the agreement as a review aid; the user still decides, and `--check-text` reports it without writing anything.

### 4.2 Existing destination copy

User-facing choices: **Overwrite**, **Ask me**, **Never overwrite (skip)**. Proposed initial default: Ask me, since the exact initial choice was not finalized. It must be configurable and must not be hard-coded to skip all existing copies.

Overwrite means reconvert the original and replace the previous output only after successful processing and validation. A failure leaves the previous output intact. Ask offers an explicit per-item decision and an optional apply-to-this-batch choice; batch choices do not silently change saved preferences.

In a truly noninteractive CLI run, an Ask policy must never hang or silently authorize replacement. Require an explicit CLI override or return a documented action-required outcome. A GUI drop launch may display a prompt.

### 4.3 Output publication guarantees

Use staging in the destination filesystem, validate the PDF, then publish with atomic replacement/no-clobber semantics appropriate to the policy. Reject any destination that aliases an original, including symlinks/hard links and case-normalized collisions. Handle full disks, locked destinations, lost mounts, and permission failures without deleting valid prior files. Do not require hard-link support as the only way to operate on common removable drives; specify tested filesystem behavior and fallback guarantees.

Signed or encrypted documents need explicit handling. Do not bypass protection or silently invalidate signatures. Reject signed and unsupported protected inputs clearly and preserve originals. *Owner decision (2026-11-10, ADR 0011):* a password-protected PDF is processed only with the password the user supplies, and its copy is protected with the same password and permissions; a PDF that opens freely but carries owner restrictions is processed only when the user opts in, and its copy keeps those restrictions.

## 5. OCR, language, and preprocessing

Bundle English and German language data for the first release. Proposed default selection: `eng+deu`; validate quality/performance on representative monolingual and bilingual fixtures. UI language and OCR language are independent settings.

Support an extensible language registry and engine capability discovery. Do not claim “all languages” means all trained data is bundled or that every script is recognized equally well. Additional language packs and alternative engines are later work unless cheap to support safely in the first package.

A first-page probe may become an optional hint; it must not select one language for an entire mixed-language document without evidence. Automatic detection and page-level language selection are deferred research. Tesseract language configuration is not reliable language detection. Statistics must distinguish configured languages from independently detected languages.

Provide optional deskew and orientation correction. Proposed default: both off until the test corpus demonstrates a suitable default. Expose their effect in plain language. Avoid aggressive image cleanup that may erase marks, signatures, stamps, or fine print. Ordinary searchable PDF is the initial output; archival PDF/A is not required.

Measure output quality through extracted words, page count, selectable text placement, and representative rendered-page comparisons. Exact OCR text is not guaranteed for handwriting, poor scans, or unsupported scripts.

## 6. Portable settings and UI

### 6.1 Settings contract

Use a readable, versioned settings file beside the installed application; proposed format/name: `searchify-pdf.settings.json`. Persist validated configuration atomically. Include a schema version, migration support, sensible bounds, and recovery for malformed files. Never execute settings contents.

A single-file distribution means one downloadable/runnable application artifact with dependencies bundled. User-created settings and optional statistics are separate mutable files by design; they are not extra dependency installations.

Find the real application location, not the current working directory, shortcut directory, or temporary extraction directory. For macOS, put the settings file beside the `.app` bundle, not inside its signed contents. Launching from a read-only image or a non-writable application directory must produce useful guidance.

### 6.2 Save and close behavior

- **Save:** validate and write current settings, replacing the previous settings only on success.
- **Close with unsaved changes:** ask Save / Discard / Cancel. Do not silently save or silently discard.
- **Write failure:** show the error and keep unsaved changes available. Do not claim success or erase the previous valid configuration.
- **Read-only location:** explain how to move the application to a writable folder. Do not silently fall back to a user-profile configuration file; that would defeat portable settings.
- **Concurrent settings edits:** detect stale versions or serialize writes; avoid silent lost updates.

A user-profile fallback is not a default. Decision (issue #9, ADR 0012): the user may explicitly opt in to storing settings in the user profile (confirmed button when the application folder is read-only, or `--store-settings-in-profile`); a settings file beside the application always takes precedence.

### 6.3 Settings surface

OCR languages; preprocessing; existing-OCR policy; existing-output policy; output suffix; worker mode/count; statistics toggle; theme; UI language. Recursive folder behavior is required, not a default-off checkbox. Any optional depth/exclusion controls are later enhancements and must not change the expected recursive default.

The UI must stay responsive during OCR and expose per-file status and aggregate progress. Use a restrained colorful visual design with clear hierarchy, light/dark themes, good contrast, keyboard access, scalable text, and no reliance on color alone. English is the default; German translations cover menus, settings, prompts, errors, progress, and summaries. Avoid hard-coded strings scattered through the processing core.

Choose the Python UI framework in an early ADR based on Linux/Windows/macOS support, packaging footprint, accessibility, licensing, and native open-event integration. PySide/Qt or another suitable framework may be evaluated; this document does not mandate an untested dependency choice.

## 7. Scheduling and performance

Provide **Auto**, **Sequential**, and **Fixed concurrent documents** modes. Fixed mode accepts a positive integer within a documented practical bound. The user's examples of 3–5 jobs are examples, not a hard cap.

Auto estimates a conservative worker count from available CPU and memory; it is not a claim to benchmark system power precisely. Make the chosen count visible. Reassess resource pressure conservatively and preserve UI responsiveness.

Prevent nested parallelism from multiplying CPU and memory use: document workers, engine page workers, and Tesseract threads share one budget. Use a bounded queue and isolated workers; avoid loading all PDFs into memory. Test cancellation, child-process cleanup, and workers crashing. Set explicit engine timeout policies and report timeouts/partially processed pages; a PDF existing on disk is not proof of complete OCR.

Create reproducible benchmark fixtures and record platform, engine version, language data, page types, job count, CPU/memory, wall-clock duration, and peak memory. Establish baselines before inventing absolute speed targets. Performance tests should use justified regression tolerances rather than brittle exact timing assertions.

## 8. Optional local statistics

Disabled by default. When enabled, persist statistics locally beside the application in a separate versioned file/database. Disabling stops new collection; offer a clear Reset/Delete action. Do not transmit statistics or document contents. Runtime progress and immediate summaries still work with persistence disabled.

Required metrics when enabled:

- PDFs attempted/processed, successfully converted, preserved/copied, skipped, failed, and cancelled.
- Pages inspected, actually OCR-processed, preserved, skipped, and failed where the engine exposes those facts.
- Configured OCR languages and frequency; detected language only when an independent detector provides evidence, otherwise label it unknown/not measured.
- Per-document processing duration, per-page OCR duration when measurable, and separate queue/wall-clock timings where useful.
- Count, total, mean, and median for PDF and page timing distributions; retain enough measurements to calculate true medians. Do not compute a median of batch averages as a global median.

If the engine does not expose page timings, show an explicitly labeled estimate or “unavailable”; never label total duration divided by page count as measured per-page duration. Parallel page durations may sum to more than elapsed wall time. Define treatment of failures, retries, and cancelled jobs to prevent double-counting.

Store no recognized text or full source paths by default. Handle a statistics write failure visibly without discarding a successfully converted PDF. The polished statistics dashboard can follow the core MVP, but instrument trustworthy event boundaries early.

## 9. Proposed architecture

Keep business logic usable without the GUI. Use typed interfaces and dependency injection at external boundaries, avoiding unnecessary framework machinery.

| Component | Responsibility |
| --- | --- |
| Desktop UI / CLI adapters | Inputs, localized presentation, user decisions; no OCR business logic |
| Platform launch adapters | Windows argv, macOS open events, Linux desktop launchers, app location |
| Application workflow | Settings snapshot, discovery, policies, job lifecycle, result summaries |
| Scheduler | Bounded concurrency, resource budget, cancellation, child-process management |
| OCR engine interface | Capabilities, validation, conversion, progress events, result metadata |
| OCRmyPDF adapter | Engine-specific options, subprocess/library interaction, version compatibility |
| Output publisher | Source preservation, staging, validation, locking, final publication |
| Settings repository | Portable paths, schema validation, migrations, atomic writes |
| Statistics repository | Opt-in local metrics and aggregation |
| Packaging / component inventory | Runtime dependencies, language data, license information, build identity |

Suggested module areas under `src/searchify_pdf`: `ui`, `platform`, `application`, `domain`, `engines`, `storage`, `cli`. Keep interfaces small and make engine limitations explicit. External engine execution should use argument arrays rather than shell interpolation. Ensure packaged subprocess invocation does not accidentally relaunch the frozen GUI as if it were a Python interpreter.

Proposed lifecycle: discovered → policy decision → queued → running → validating → publishing → completed, with skipped/failed/cancelled terminal outcomes. Emit typed events for UI and statistics. Prompt services must marshal decisions to the UI thread while workers wait safely.

Use ADRs for GUI toolkit, bundler, process strategy, output atomicity, native drop integration, language distribution, and licensing. Review/adapt architecture after a real packaged vertical slice; do not spend the entire MVP building abstractions for speculative engines.

## 10. Platform packaging and rollout

| Priority | Target | Intended artifact | Evidence required |
| --- | --- | --- | --- |
| 1 | Linux x86-64 | Single self-contained artifact, e.g. AppImage or validated equivalent | Run OCR without development dependencies; test declared distributions/desktops |
| 2 | Windows 10 and 11 x64 | Self-contained `.exe` | Packaged execution plus explicit Windows 10/11 compatibility tests |
| 3 | macOS Intel x64 and Apple Silicon arm64 | `.app` presented as one application, delivered in a suitable signed archive/image | Native execution on both architectures plus Finder open/drop checks |

One identical binary cannot serve all targets. Separate artifacts per OS/architecture are expected; universal macOS packaging is optional if validated. A macOS application bundle is internally multiple files but appears as one application in Finder. Document this platform distinction rather than promising a literal lone executable with native behavior everywhere.

Bundle Python runtime, OCR/PDF dependencies, native libraries, language data, fonts/assets as needed, and required notices. No separate Python/Tesseract installation for end users. Validate temporary extraction behavior, paths with spaces, offline use, architecture compatibility, permissions, and launches from shortcuts. Do not assume the newest Python/dependency versions still support Windows 10: choose and test the supported baseline explicitly.

Dropping onto an executable icon is not uniformly implemented by all desktops. Windows normally supplies command-line paths. macOS requires native file-open handling and app metadata. Linux requires documented launcher integration; a raw ELF/AppImage drop is not guaranteed in every file manager. Publish a tested desktop matrix and include file/folder selection as a universal fallback.

## 11. Test strategy and quality gates

Use Black for formatting and Ruff for linting, with compatible rules and no competing formatters. Add static type checking (proposed: mypy), pytest, coverage.py, and a suitable mutation tool validated against the chosen Python version. Lock development and runtime dependencies; keep a repeatable documented developer setup.

**Coverage target: at least 98%; hard minimum: 95% for both statement and branch coverage of first-party Python code.** Enforce metrics separately so a combined percentage cannot hide weak branch coverage. Focus especially on policies, settings, scheduling, and publication. Cover native adapters and UI behavior through integration/E2E tests where unit coverage cannot prove behavior. Narrow exclusions must be justified and reviewed; do not exclude difficult modules to reach a number. Third-party/bundled/generated code is not part of the denominator.

Mutation testing must demonstrate that assertions catch changed behavior, not merely execute lines. Run targeted mutation checks on relevant PR changes where practical and broader checks on a schedule/before releases. Establish an explicit mutation-score baseline and threshold after tooling validation; no numerical mutation threshold has yet been agreed. Review surviving mutants and distinguish equivalent mutants from missing tests. Coverage is not a substitute.

### Required automated test layers

1. Unit/property tests: path mapping, policies, configuration validation/migrations, statistics calculations, scheduler bounds, collision detection.
2. Integration: actual OCR on synthetic scanned PDFs, mixed digital/scanned pages, redo behavior, both languages, preprocessing, engine failures, cancellation.
3. Packaged E2E: execute the produced application artifact on a native target host, with development tools absent from its runtime path; verify output text, page counts, source checksums, and portable settings behavior.
4. UI: save/close prompts, write failures, localization, themes, progress, cancellation, and native open events where automation is reliable.
5. Fault/adversarial tests: read-only/full destinations, corrupted PDFs/configuration, unusually large pages, process crashes, filename collisions, long/Unicode paths, symlink loops, simultaneous instances, interruption during publication, and malformed launch arguments.
6. Performance: bounded workers/memory, sequential vs parallel corpus runs, accurate timings and medians.

Keep fixtures synthetic or permissively licensed, with known expected words, dimensions, and language content. Never commit personal contracts or credentials. OCR assertions should use expected phrases and sensible tolerances, not byte-identical engine output across versions.

A red-team review follows the first working prototype. Examine input handling, overwrites, untrusted PDF/resource exhaustion, subprocess boundaries, bundled dependency risks, settings corruption, and release tampering. Convert findings into reproducible tests/issues and revisit the architecture. Do not describe a packaged local parser as a security sandbox.

## 12. GitHub repository and pipelines

Agents should create a normal reviewable repository containing `pyproject.toml`, a dependency lock, `src/`, `tests/`, fixture/benchmark generators, packaging scripts, `.github/workflows/`, README, this VISION.md, CONTRIBUTING, SECURITY, changelog/release notes, ADRs, component notices, and a license once the owner chooses it.

Break implementation into issues and small PRs with acceptance criteria. Reference requirement IDs from section 15. An exploratory scaffold is not the product specification. Do not copy earlier CLI defaults that contradict this document.

### Workflow plan

| Workflow | Trigger | Checks / artifacts |
| --- | --- | --- |
| Quality | Pull requests and main-branch pushes | Black check, Ruff, types, unit tests, separate statement/branch thresholds |
| OCR integration | PRs/main; native target matrix as introduced | Real OCR fixtures, failures, mixed text, originals unchanged |
| Package smoke | Main and relevant PRs | Build artifact then execute that artifact; retain logs and test reports |
| Mutation | Relevant PR scope plus scheduled/full pre-release run | Mutation reports, surviving-mutant review |
| Dependencies/security | Scheduled and dependency changes | Lock updates, dependency scanning, component inventory/license changes |
| Release | Reviewed version tag or manual dispatch for a verified commit | Required checks, native builds, packaged tests, checksums, SBOM/notices, draft release |

Use explicit, supported runner OS/architecture labels rather than assuming `latest` stays on the same architecture. Select exact labels when implementation begins. GitHub currently offers native Linux/Windows/macOS hosts, including Intel and arm64 macOS; availability and billing depend on repository/account settings. Hosted Windows runners are not automatically proof of Windows 10 and Windows 11 x64 desktop support.

Linux containers are useful for reproducible Linux tests; they do not prove native Windows/macOS compatibility. Use actual target OS runners/VMs for those platforms. Windows 10/11 validation may use licensed VMs or suitable hosted desktop runners. macOS validation needs supported Mac-hosted infrastructure; do not promise ordinary Linux Docker containers can run and validate macOS apps.

Use headless GUI testing on Linux where feasible. Native desktop drag/drop and appearance need automated interaction tests or documented manual/remote-host checks. Lack of personal Windows/Mac hardware must not block Linux MVP. Record missing evidence as a limitation and recruit testers later if necessary.

Pipeline security: minimal permissions, pinned action revisions with managed updates, no release secrets in untrusted PR jobs, no privileged execution of fork code, protected publishing credentials, and provenance linking artifacts to tested commits. Treat self-hosted runners as privileged infrastructure, not disposable safe targets for arbitrary public PRs.

## 13. Public release requirements

Use versioned prereleases for prototypes, e.g. `v0.1.0-alpha.1`. Build from a tagged, reviewed commit with locked dependencies. Each asset name identifies product, version, OS, and architecture. Include checksums, release notes, known limitations, component inventory/SBOM, and legally required notices/source offers or source materials where applicable.

Default release workflow creates a draft; a maintainer reviews evidence and publishes. Public binary releases can be Linux-only initially. Do not list untested Windows/macOS binaries as supported just because they compiled. Promote artifacts already tested, rather than rebuilding an unrelated artifact at publication time. Signing/notarization changes must also be validated before promotion.

The About and Licenses UI works offline and lists the application version plus bundled components' names, exact versions, authors/copyright holders, project URLs, license identifiers/texts, and required notices. Generate this inventory from actual build inputs and include native dependencies and trained data, not only Python packages.

Before public distribution, review redistribution obligations for the exact bundled stack, including OCRmyPDF, Tesseract, PDF renderers, GUI toolkit, fonts, language data, and transitive dependencies. Attribution alone may not satisfy every license. Select compatible dependencies and comply with source/notice obligations. Commercial use is a later product choice, but distribution compliance cannot be deferred past public release. This is a release checklist, not a legal conclusion about a chosen bundle.

Name/trademark/domain availability for Searchify PDF remains unchecked; keep it a working title until reviewed. Code signing, notarization, publisher identity, repository ownership/visibility, and project license are release decisions requiring the owner's input.

## 14. Milestones and deferred issue backlog

### M0 — Implementation preparation

Create the repository structure, requirements-linked issues, ADR skeletons, lock strategy, and initial quality pipeline. Resolve a viable Python/UI/bundler combination through a small Linux packaging spike. Confirm legal/dependency feasibility before investing in a bundle that cannot be distributed as intended.

### M1 — Linux vertical slice / MVP

One self-contained Linux application converts one PDF and a recursive folder into adjacent suffixed copies. Add settings UI and portable save semantics, conflict policies, real OCR, progress/results, cancellation, bundled English/German data, and packaged smoke tests. Keep interfaces ready for themes/translations and statistics. Basic usability is required; elaborate visual polish is not a reason to delay the first working slice.

### M2 — Linux hardening and first public prerelease

Complete English/German UI, light/dark themes, worker modes, optional truthful statistics, fault handling, coverage gates, mutation baseline, red-team review, and release inventory. Validate declared Linux desktops and publish only after prerelease gates pass. Features incomplete in the earliest internal MVP must have explicit follow-up issues, not disappear from scope.

### M3 — Windows

Produce the bundled executable; validate packaged OCR, portable settings, Explorer drop/shortcut behavior, and Windows 10/11 target hosts. Document Windows indexing setup and test content search separately from OCR generation.

### M4 — macOS

Deliver and test Intel and Apple Silicon applications, native open/drop events, adjacent settings, bundle-aware resource resolution, signing/notarization strategy, and native-host E2E evidence. Use remote hosts/testers for remaining interactive checks.

### Deferred issues to create during repository setup

| Issue | Scope / acceptance direction |
| --- | --- |
| User-triggered self-update | Button checks trusted release source, downloads and verifies matching OS/architecture asset, replaces safely via platform-appropriate helper/restart, preserves settings, supports rollback; no MVP implementation. Stage 1 (ADR 0014): on request, check GitHub's latest release and offer its download page; nothing downloaded |
| Additional OCR languages | Manage packs with verified provenance; script-aware quality tests and offline behavior |
| Language detection | Evaluate page-level mixed-language handling; never infer an entire document solely from its first page |
| Additional engines | Implement adapter without rewriting UI/workflow; compare accuracy, speed, licensing |
| Existing-OCR quality cross-check | Meaningful quality signals and user review; avoid treating text presence as quality — implemented as agreement with a fresh recognition (ADR 0013) |
| Expanded desktop testing | Recruit Windows/macOS/Linux testers; publish repeatable test script and supported matrix |
| Monetization exploration | Evaluate only after a useful prototype and user feedback; no account/payment machinery now |
| Optional user-profile settings fallback | Consider only as explicit opt-in without breaking portable mode — implemented as such (ADR 0012) |

Do not create an external issue or imply one exists during this document-only handoff. Agents should create them once repository ownership and access are established.

## 15. Acceptance and evidence matrix

| ID | Requirement / check | Expected evidence |
| --- | --- | --- |
| A01 | Scanned PDF gains selectable/searchable expected words | Real OCR fixture plus extracted-text assertions |
| A02 | Originals never change | Checksums before/after successful, failed, cancelled, and overwrite runs |
| A03 | Recursive adjacent output; no output directory | Nested-folder E2E including spaces/Unicode |
| A04 | Generated copies not recursively consumed | Repeated-run test; suffix-change behavior and explicit override tests |
| A05 | Existing OCR: always/ask/never | Mixed-content fixtures, prompt tests, no silent force-rasterization |
| A06 | Existing destination: overwrite/ask/never | Policy tests including preservation after failed replacement |
| A07 | Save / close / failure behavior | UI and storage tests; malformed/read-only settings cases |
| A08 | Settings travel with app | Relocation/shortcut test; no writes to extraction dir or silent profile fallback |
| A09 | Drop uses saved settings; normal launch opens UI | Native launch tests per supported platform |
| A10 | Standalone execution with bundled dependencies | Packaged E2E on clean/restricted-runtime host, offline after download |
| A11 | Responsive UI, themes, English/German | UI checks and documented visual/accessibility review |
| A12 | Auto/sequential/fixed workers remain bounded | Scheduler tests, process-tree measurements, cancellation cleanup |
| A13 | Statistics off by default and accurate when enabled | No persistent collection when off; count/mean/median fixtures and error tests |
| A14 | Failure-safe publication and collisions | Race, disk, permission, alias, and interruption tests |
| A15 | 95% minimum / 98% target statement and branch coverage | Separate CI reports; reviewed exclusions |
| A16 | Mutation, integration, and packaged E2E checks | Mutation baseline/report plus real behavior tests |
| A17 | Native target evidence matches advertised support | OS/architecture results; documented desktop/manual gaps |
| A18 | Public releases are traceable and compliant | Tag/commit, tested assets, checksums, notices/inventory, maintainer review |
| A19 | Windows can find body-text keyword | Configured local Windows indexing test; distinguish OCR success from index configuration |
| A20 | Adversarial review findings addressed | Reproducible cases, issues, fixes, regression tests |

Windows Search requires an appropriate PDF content filter and indexing settings in addition to embedded text. Provide user instructions to include folders, enable PDF content indexing, and test a known body-only keyword. Do not modify system indexing settings automatically or promise immediate indexing of network/cloud-only files.

## 16. Remaining decisions and when to resolve them

| Decision | Resolution point |
| --- | --- |
| GUI toolkit, bundler, Python baseline, dependency pins | M0 technical spikes and ADRs |
| Minimum Linux distribution/glibc and supported desktops | Before claiming Linux release support |
| Exact macOS minimum versions per architecture | Before M4 packaging, using current dependency/toolchain support |
| Default output-conflict policy | Proposed Ask; validate UX before first external build |
| Exact Auto heuristic, performance tolerances, mutation threshold | Establish with measured M1/M2 baselines |
| Final stats storage format/retention and optional page timing availability | Before exposing persistent statistics |
| Publisher/repository owner, license, signing credentials and budget | Before public distribution |
| Trademark/name availability | Before committing to a public brand |

These are implementation/release decisions, not invitations to reopen settled recursive behavior, adjacent outputs, portable settings, or the Linux-first order.

## 17. Handoff instructions for implementation agents

1. Read this document and turn milestones into linked issues; do not start by publishing binaries.
2. Capture ADRs for consequential choices, then build a thin Linux vertical slice early.
3. Establish explicit interfaces before dividing work into UI, OCR, persistence, packaging, and tests. Assign clear ownership to avoid conflicting edits.
4. Keep PRs reviewable, with behavior changes, tests, validation evidence, and requirement IDs.
5. Reconcile ambiguities against the latest decisions here. Ask only when a consequential choice cannot be safely inferred; label proposed defaults.
6. Run packaged artifacts, not just Python source tests. Never present CI configuration as proof that CI has passed.
7. Use synthetic fixtures, report limitations honestly, and review architecture after evidence from the prototype and adversarial testing.
8. Finish each milestone with a short evidence report: implemented requirements, checks passed, remaining risks, and next issues.

## 18. Consolidation review

This revision was checked against the conversation and reviewed for conflicting requirements:

- Removed the earlier folder `output` policy: all copies now live beside originals.
- Replaced optional recursion with required recursive discovery.
- Replaced profile-based settings with portable adjacent settings and explicit save-failure handling.
- Replaced CLI-only/source-install delivery with a desktop UI and bundled platform applications.
- Separated OCR replacement from destination overwrite, preserving all three choices for each.
- Clarified the distinction between one application artifact and mutable settings/statistics files.
- Retained both Intel and Apple Silicon macOS targets, with Linux first and explicit support evidence.
- Kept language detection, updater, and monetization deferred without losing them from the backlog.
- Added timing/median semantics, nested-concurrency limits, packaging tests, and truthful CI/release claims.
- Marked unchosen defaults, technologies, thresholds, and legal/release decisions as open or proposed.

No claim is made here that these requirements are already implemented or that any public release, remote pipeline run, external issue, license approval, or native desktop test has occurred.

## 19. Technical reference starting points

Checked for this revision on 9 November 2026; implementers must revalidate versions and runner availability at setup time.

- [OCRmyPDF installation and requirements](https://ocrmypdf.readthedocs.io/en/latest/installation.html)
- [OCRmyPDF modes and existing-text handling](https://ocrmypdf.readthedocs.io/en/latest/advanced.html)
- [OCRmyPDF cookbook and preprocessing](https://ocrmypdf.readthedocs.io/en/latest/cookbook.html)
- [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [Choosing runner OS and architecture](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job)
- [GitHub macOS Intel and Apple Silicon runner announcement](https://github.blog/changelog/2026-02-26-macos-26-is-now-generally-available-for-github-hosted-runners/)
- [Windows Search indexing](https://support.microsoft.com/en-us/windows/experience/performance-optimization/search-indexing-in-windows)
- [Windows Search filters](https://learn.microsoft.com/en-us/windows/win32/search/-search-ifilter-about)
