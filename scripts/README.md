# scripts/

Small, reusable helper scripts. Each script documents its own usage in its header
(`--help` where applicable). All scripts are run from any directory; they locate the
repository root themselves.

| Script | Purpose |
| --- | --- |
| `../localPipeline.sh` | The full quality gate (format, lint, types, headers, tests + coverage, wheel, binary, packaged E2E, Docker, optional mutation). CI runs the same script. |
| `bump_version.py` | Bump SemVer (`patch`/`minor`/`major`) in `src/searchify_pdf/_version.py` and add a CHANGELOG entry. `--show` prints the version. |
| `commit.sh` | Bump → run pipeline → commit (Conventional Commit message enforced) → push. Reverts the bump when the pipeline fails. |
| `check_coverage.py` | Enforce statement **and** branch coverage thresholds separately from `coverage.json`. |
| `check_headers.py` | Verify SPDX GPL-3.0-or-later + copyright headers on all first-party `.py`/`.sh` files. |
| `fetch_tessdata.sh` | Download pinned, checksum-verified Tesseract eng/deu/osd data plus the configs OCRmyPDF needs. |
| `install_ci_dependencies.sh` | Install Tesseract and Qt runtime libraries on a Debian/Ubuntu CI runner. |
