# 0014 — User-triggered update check (self-update, stage 1)

- Status: accepted (issue #2 stage 1; VISION §15 backlog "User-triggered self-update")
- Date: 2026-11-10

## Context
Users of the portable executables had no way to learn about a new release except by
visiting GitHub. VISION lists a full self-update (download, verify, replace, restart,
rollback) as a later item. Two things block the full version today:

- **Trust.** `SHA256SUMS` comes from the same release as the executable, so it detects
  a damaged download but not a tampered release. Replacing the running program safely
  needs a signature checked against a key built into the app, which depends on the
  signing decisions in #12.
- **Privacy.** The app works offline and uploads nothing; any network access must be
  something the user asked for.

The operating systems' built-in update mechanisms do not fit a plain one-file
executable: MSIX/App Installer (Windows) and Sparkle (macOS) need signed packages and
feeds, while on Linux, updates come from package managers, Flatpak/Snap or AppImageUpdate.

## Decision
Stage 1 checks the version, and the user installs the update:

- **Only on request:** *Check for updates* on the About tab, `--check-update` on the
  command line. Never at start-up, never in the background.
- **One request:** `GET https://api.github.com/repos/marcelpetrick/SearchifyMyPDF/releases/latest`
  with `Accept` and a generic `searchify-pdf/<version>` client name; no account, no other
  identifiers. Timeout 10 s, answer capped at 1 MB. Drafts and pre-releases are never
  offered (the endpoint excludes them, and pre-release tags are rejected).
- **TLS through the operating system's certificate store** (`truststore`, MIT), so the
  frozen executables verify GitHub's certificate like a browser on the same machine,
  including company proxies with their own root certificate. A bundled CA list would
  ignore those, and OpenSSL's built-in default paths differ between Linux distributions.
- **Compare numerically** (`0.10.0` > `0.9.0`). If a newer version exists, the app shows
  both versions and offers to open that release's page in the browser. Only
  `https://github.com/marcelpetrick/SearchifyMyPDF/releases/…` URLs are opened; anything
  else in the answer falls back to the releases page.
- **Nothing is downloaded or replaced.** Failures (offline, TLS, rate limit, unexpected
  answer) become a message; the check never raises.
- The GUI runs the check on a daemon thread and delivers the result through a Qt signal,
  so the window stays responsive and closing it never waits for the network.

## Stage 2 (later, after #12)
"Download and restart": pick the asset for this OS and architecture, verify
`SHA256SUMS` **and** a signature with an embedded public key, write the new file beside
the running one, then swap it in. Linux and macOS use an atomic `os.replace` followed by
a restart. Windows renames the running `.exe` to `.old`, moves the new file into place,
starts it, and deletes `.old` on the next start. Stage 2 runs only when no batch is
running and the folder is writable; otherwise it falls back to stage 1.

## Consequences
- New runtime dependency `truststore` (pure Python, MIT, listed in the inventory).
- The CLI exits 1 when the check fails, so scripts can tell "up to date" from "unknown".
- The packaged E2E and Docker tests stay offline; the check is unit- and UI-tested with
  injected answers. The native release smoke tests call the real endpoint once, which
  exercises TLS in the frozen Windows and macOS executables.
