# Platform and desktop evidence matrix (A17)

Only rows with automated or recorded evidence are claimed as supported.

| Target | Artifact | Evidence | Status |
| --- | --- | --- | --- |
| Linux x86-64, glibc ≥ 2.35 | `searchify-pdf-<v>-linux-x86_64` | CI + local: packaged E2E in clean offline Ubuntu 22.04 (CLI, portable settings, read-only app dir, GUI offscreen drop launch) | ✅ supported |
| Manjaro (glibc 2.44), KDE | same | Developer machine: real OCR, UI, screenshots | ✅ |
| Ubuntu 24.04 (GitHub runner) | source + wheel | CI pipeline incl. UI offscreen | ✅ |
| Drop onto launcher (GNOME Shell dock, KDE Plasma panel/menu) | `--install-desktop-entry` | Launcher file validated by tests; interactive drop not automated | 🟡 manual check pending |
| Drop onto raw executable in file managers | — | Not uniformly supported by Linux file managers | ❌ use launcher/window |
| Docker (Linux x86-64 containers) | `ghcr.io/marcelpetrick/searchifymypdf` | `scripts/docker_smoke.sh` in CI; public image also tested with Compose | ✅ CLI only |
| Windows x86-64 | `searchify-pdf-<v>-windows-x86_64.exe` | Windows Server 2022 runner: unit, UI and OCR integration tests; executable smoke test | 🟡 preview (M3) |
| macOS 15+ Apple silicon | `searchify-pdf-<v>-macos-arm64` | macOS 15 runner: unit, UI and OCR integration tests; executable smoke test | 🟡 preview (M4) |
| macOS Intel | — | Pending native build and tests | ⏳ M4 |
