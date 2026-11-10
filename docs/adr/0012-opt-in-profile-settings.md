# 0012 — Opt-in user-profile settings

- Status: accepted (issue #9; VISION §6.2/§14 allow it only as an explicit opt-in)
- Date: 2026-11-10

## Context
Settings travel with the application (ADR 0008). An application folder that cannot be
written (e.g. `/opt`, `C:\Program Files`, a read-only share) so far only produced
guidance to move the app. Some users cannot move it; for them a per-user folder is the
only place left. VISION forbids a *silent* fallback because it would quietly defeat
portable settings.

## Decision
- **Portable stays the default.** Order: `SEARCHIFY_PDF_HOME` → a settings file beside
  the application → the user-profile folder **if the user opted in** → beside the
  application (`storage/settings_location.py`).
- **The opt-in is explicit and recorded by the file itself:** the GUI offers
  *Store settings in my user profile* only when the app folder is read-only and asks
  for confirmation; the CLI has `--store-settings-in-profile` (saves the effective
  settings, options included). Without that action nothing is ever written to the
  profile.
- **A settings file beside the application always wins**, so switching back is just
  saving there again (GUI *Store settings next to the app again* when the folder became
  writable). The profile copy is left in place but no longer read.
- Profile folders: Windows `%APPDATA%\Searchify PDF`, macOS
  `~/Library/Application Support/Searchify PDF`, otherwise
  `$XDG_CONFIG_HOME/searchify-pdf` (`~/.config/searchify-pdf`), created with mode 0700.
- Statistics follow the settings folder in use.
- With `SEARCHIFY_PDF_HOME` set (tests, Docker `/config`) the profile is never used and
  the CLI opt-in is refused (exit 2).

## Consequences
- A08 still holds: no write outside the app folder unless the user chose it.
- Packaged E2E `test_profile_settings_are_an_explicit_opt_in`: read-only app folder,
  nothing in the profile before the opt-in, settings used from the profile after it,
  app folder untouched.
