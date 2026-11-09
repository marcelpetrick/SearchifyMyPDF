# Platform and desktop evidence matrix (A17)

Only rows with automated or recorded evidence are claimed as supported.

| Target | Artifact | Evidence | Status |
| --- | --- | --- | --- |
| Linux x86-64, glibc ≥ 2.35 | `searchify-pdf-<v>-linux-x86_64` | CI + local: packaged E2E in clean offline Ubuntu 22.04 (CLI, portable settings, read-only app dir, GUI offscreen drop launch) | ✅ supported (prerelease) |
| Manjaro (glibc 2.44), KDE | same | Developer machine: real OCR, UI, screenshots | ✅ |
| Ubuntu 24.04 (GitHub runner) | source + wheel | CI pipeline incl. UI offscreen | ✅ |
| Drop onto launcher (GNOME Shell dock, KDE Plasma panel/menu) | `--install-desktop-entry` | Launcher file validated by tests; interactive drop not automated | 🟡 manual check pending |
| Drop onto raw executable in file managers | — | Not uniformly supported by Linux file managers | ❌ use launcher/window |
| Docker (any x86-64 host) | `ghcr.io/marcelpetrick/searchifymypdf` | `scripts/docker_smoke.sh` in CI | ✅ CLI only |
| Windows 10/11 x64 | — | none | ⏳ M3 (not supported) |
| macOS Intel / Apple Silicon | — | none (open-event code present) | ⏳ M4 (not supported) |
