# 0015 — Drop launch works in the background

- Status: accepted (owner request 2026-11-11; refines VISION §3.1)
- Date: 2026-11-11

## Context
Dropping PDFs or folders on the launcher opened the full window every time, although
the settings were already chosen and the copies land beside the originals. The owner
wants "drop and done": no window unless asked for.

## Decision
- **Drop launch** (paths from the OS: launcher `%F`, drop on the executable, "Open with")
  processes with the saved settings **without showing the window**.
  - Questions the settings require (password, "overwrite the existing copy?", existing
    text with "Ask me") still appear as dialogs.
  - All succeeded: the app quits silently (exit 0).
  - Anything failed, cancelled or needing a decision: one message lists the summary and
    offers *Show the window with the details*; No quits with exit 1.
- **Opt-in** setting `show_window_on_drop` (*Show this window when PDFs or folders are
  dropped onto the app*, default off) restores the old behaviour.
- **Start without paths** (double-click) always opens the window; drops onto the open
  window are processed there as before.
- `--cli` and `--gui-smoke-test` are unchanged.

## Consequences
- Quitting on the last closed window is disabled during a background run, so closing a
  question dialog does not end the batch.
- macOS delivers Finder drops as open events after start; until #11 the preview keeps
  showing the window there (the app has no paths at launch).
- Tested: UI tests for success, problems (show / quit) and a second batch; packaged E2E
  on a real X server: default drop maps no window and the process exits by itself, the
  opt-in maps the window.
