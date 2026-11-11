# Mutation testing baseline

Tool: **mutmut 3.8.1** on Python 3.12 (`scripts/run_mutation.sh`, configuration in
`[tool.mutmut]` of `pyproject.toml`). Run locally with `./localPipeline.sh --mutation`;
GitHub runs it weekly and on demand (`.github/workflows/mutation.yml`).

## Scope

Mutated: the decision-heavy core whose bugs would silently do the wrong thing —
`domain/` (settings, policies, path rules, outcomes), `application/discovery.py`,
`application/scheduler.py`, `storage/statistics.py`, `storage/settings_repository.py`,
`storage/publisher.py`.

Not mutated (covered by UI, integration with real OCR, and packaged E2E tests instead):
UI, CLI, engine adapter and worker, platform adapters, i18n catalogs, the threaded
workflow orchestrator, lock and atomic-write primitives (exercised heavily by
workflow/fault tests; mutating sleep/timeout code mostly yields timing-only mutants).

## History

| Date | Mutants | Killed | Reviewed equivalent | Survived | Score |
| --- | --- | --- | --- | --- | --- |
| 2026-11-10 first run | 998 | 785 | 0 | 213 | 78.7 % |
| 2026-11-10 after review | 998 | 979 | 19 | 0 | 100 % of non-equivalent |
| 2026-11-11 first GitHub run | 1125 | 1101 | 19 | 5 | 99.5 % |
| 2026-11-11 after review | 1125 | 1105 | 20 | 0 | 100 % of non-equivalent |

The first run showed weak assertions on error *details* (codes were checked, the
offending values were not), incomplete round-trip checks of the statistics file,
unasserted omission paths in discovery, and missing boundary checks. Tests were added in
`tests/unit/test_mutation_hardening.py`.

The 2026-11-11 run (the first one on GitHub, after the profile-settings and protected-PDF
work) left five survivors: unasserted `app_dir`/`profile_dir` fields of the resolved
settings home, the untested default password of `validate_output`, and one equivalent
`sample_pages` boundary (at exactly the limit, both branches return every page).

## Threshold

**Minimum mutation score: 95 %** of non-equivalent mutants (enforced by
`scripts/mutation_score.py`). Equivalent mutants are listed with reasons in
`docs/mutation-equivalent.txt`; adding to that list requires a review comment explaining
why the mutant cannot change observable behaviour.
