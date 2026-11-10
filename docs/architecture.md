# Architecture

Searchify PDF is a local desktop application (plus headless CLI and Docker image) that
writes a searchable copy next to every scanned PDF. This page describes it with the
[C4 model](https://c4model.com/) (context → containers → components), the key runtime
flows, and the delivery pipeline. Decisions are recorded in [`docs/adr/`](adr/).

## C1 — System context

```mermaid
C4Context
    title System context — Searchify PDF
    Person(user, "Computer user", "Non-technical; drops scanned PDFs or folders")
    Person(admin, "Batch operator", "Runs the CLI / Docker image on servers or NAS")
    System(app, "Searchify PDF", "Local OCR; writes <name>_searchable.pdf beside each original")
    System_Ext(fs, "Local / removable / network file systems", "Originals (read-only) and adjacent copies")
    System_Ext(desktop, "Linux desktop", "File manager, app menu launcher, drag & drop, xdg-open")
    System_Ext(search, "Desktop search / indexers", "Windows Search, GNOME Tracker, Baloo… index the embedded text")
    Rel(user, app, "Drops files/folders, changes settings")
    Rel(admin, app, "searchify-pdf --cli / docker run")
    Rel(desktop, app, "Launches with dropped paths (%F)")
    Rel(app, fs, "Reads originals, publishes validated copies")
    Rel(search, fs, "Indexes searchable copies")
```

Nothing leaves the computer: no account, no telemetry, no upload. Optional statistics are
stored beside the application.

## C2 — Containers (deployable units)

```mermaid
C4Container
    title Containers — Searchify PDF
    Person(user, "User")
    System_Boundary(sb, "Searchify PDF") {
        Container(exe, "Linux one-file executable", "PyInstaller, Python 3.12, PySide6", "GUI + CLI; bundles Tesseract, its libraries and eng/deu data")
        Container(worker, "Engine worker process", "Same executable, --searchify-engine-worker", "One OCRmyPDF conversion per document")
        Container(tess, "Tesseract", "Bundled native binary", "Text recognition per page")
        ContainerDb(settings, "searchify-pdf.settings.json", "Versioned JSON beside the app", "Portable settings")
        ContainerDb(stats, "searchify-pdf.statistics.json", "Versioned JSON beside the app", "Opt-in local statistics")
        Container(docker, "Docker image", "python:3.12-slim + Debian Tesseract", "Headless CLI, ghcr.io/marcelpetrick/searchifymypdf")
    }
    Rel(user, exe, "Uses")
    Rel(exe, worker, "Spawns (own process group, cancellable)")
    Rel(worker, tess, "Runs per page")
    Rel(exe, settings, "Reads / atomically writes")
    Rel(exe, stats, "Appends batches (when enabled)")
```

## C3 — Components (inside the application)

```mermaid
flowchart LR
    subgraph adapters["Adapters (no business logic)"]
        UI["ui/ — MainWindow, DropZone, BatchThread, theme"]
        CLI["cli/ — argparse, TerminalDecisions, exit codes"]
        PLAT["platform/ — app location, runtime, desktop launcher, inventory"]
    end
    subgraph core["Application core (Qt-free)"]
        WF["application/workflow — BatchRunner"]
        DISC["application/discovery"]
        SCHED["application/scheduler — worker plan, CPU budget"]
        DOM["domain/ — Settings, policies, paths, outcomes, events"]
        I18N["i18n — EN/DE catalogs"]
    end
    subgraph infra["Infrastructure"]
        ENG["engines/ — OcrEngine protocol, OCRmyPDF adapter, worker, pdf_inspect"]
        PUB["storage/publisher — staging, validation, no-clobber publish"]
        SREPO["storage/settings_repository"]
        STATS["storage/statistics"]
        LOCK["storage/locks — per-target lock, stale recovery"]
    end
    UI --> WF
    CLI --> WF
    UI --> SREPO
    CLI --> SREPO
    UI --> STATS
    CLI --> STATS
    UI --> I18N
    CLI --> I18N
    WF --> DISC
    WF --> SCHED
    WF --> ENG
    WF --> PUB
    WF --> LOCK
    DISC --> DOM
    WF --> DOM
    SREPO --> DOM
    PLAT -.-> UI
```

Only `ui/` imports Qt. The engine is reached through the small `OcrEngine` protocol
(`capabilities`, `readiness_problem`, `run`), so another engine can be added without
touching UI or workflow.

## Key flows

### Drop launch / Start

```mermaid
flowchart TD
    A([Paths from drop, Open-with, CLI or window]) --> B[Load saved settings → immutable snapshot]
    B --> C[Discover: recursive, no symlink traversal, exclude generated copies,<br/>dedupe, detect destination collisions]
    C --> D{Engine ready?<br/>tesseract + languages}
    D -- no --> X[All jobs FAILED: engine_missing]
    D -- yes --> E[For each candidate, sequentially]
    E --> F{Destination alias / symlink?}
    F -- yes --> FA[FAILED]
    F -- no --> G[Inspect PDF: pages with text, encrypted, signed, marker]
    G --> PW{Needs a password?}
    PW -- yes --> PA[Try known passwords, then ask<br/>3 attempts · skip · cancel all]
    PA -- unlocked --> H
    PA -- no answer / wrong --> FA
    PW -- no --> H{Signed? Restricted and not enabled?}
    H -- yes --> FA
    H -- no --> I{Copy exists?}
    I -- yes --> J{Output policy}
    J -- never --> SK[SKIPPED]
    J -- ask --> K[Prompt / CLI: action_required]
    J -- overwrite --> L
    K -- skip --> SK
    K -- replace --> L
    I -- no --> L{Existing text?}
    L -- none --> M[OCR: preserve mode]
    L -- some --> N{Text policy}
    N -- keep --> O{All pages have text?}
    O -- yes --> P[Copy unchanged → PRESERVED]
    O -- no --> M
    N -- replace --> R[OCR: redo mode<br/>never force-rasterize]
    N -- ask --> K2[Prompt] --> N
    M --> Q[[Bounded queue → worker threads]]
    R --> Q
    P --> Q
```

### Publication of one job

```mermaid
sequenceDiagram
    participant W as Worker thread
    participant L as Lock (.name.searchify-lock)
    participant E as Engine process
    participant S as Staging (.name.<token>.searchify-partial)
    participant D as Destination
    W->>L: acquire (O_EXCL, stale recovery)
    alt held by a live instance
        W-->>W: SKIPPED (locked)
    end
    W->>S: remove leftovers of interrupted runs
    W->>E: ocrmypdf source → staging (own session, timeout, cancel)
    E-->>W: exit code → reason
    W->>S: add generator marker, validate (opens, same page count)
    alt overwrite
        W->>D: os.replace(staging, destination)  (atomic)
    else no-clobber
        W->>D: os.link(staging, destination) — fails if it exists
        Note over W,D: FS without hard links: check + rename under the lock
    end
    W->>S: discard staging (always, in finally)
    W->>L: release
```

### Cancellation

```mermaid
flowchart LR
    C([Cancel / window close / Ctrl+C]) --> E[cancel Event set]
    E --> Q[queued jobs → CANCELLED]
    E --> R[running engine: SIGTERM to process group,<br/>SIGKILL after 3 s]
    R --> S[staging discarded, previous copy untouched]
    E --> P[pending prompts answer 'cancel']
```

## Delivery pipeline

```mermaid
flowchart LR
    dev([Developer / agent]) -->|scripts/commit.sh| LP
    subgraph LP["./localPipeline.sh (local and in CI)"]
        direction TB
        s1[uv sync --locked] --> s2[tessdata pinned by SHA-256]
        s2 --> s3[Black] --> s4[Ruff] --> s5[mypy --strict] --> s6[SPDX headers]
        s6 --> s7[pytest: unit · integration real OCR · UI offscreen]
        s7 --> s8[coverage: statement ≥95% AND branch ≥95%]
        s8 --> s9[wheel + sdist]
        s9 --> s10[PyInstaller binary in Ubuntu 22.04 container]
        s10 --> s11[packaged E2E in clean offline containers]
        s11 --> s12[Docker image build + smoke]
        s12 -.optional.-> s13[mutation ≥95%]
    end
    LP -->|push main| CI["Actions: Local Pipeline<br/>(py3.12 full, py3.13 no-package)"]
    LP -->|push main / tag| DK["Actions: Docker → GHCR"]
    LP -->|tag v*| REL["Actions: Release → draft release<br/>with tested binary, SHA256SUMS, inventory"]
    SCHED([weekly]) --> MUT["Actions: Mutation"]
```

All workflows pin actions to commit SHAs, run with read-only permissions by default and
grant `contents: write` / `packages: write` only to the publishing jobs.
