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
| `build_linux_binary.sh` | Build the self-contained one-file Linux x86-64 executable (PyInstaller in an Ubuntu 22.04 container) plus checksum and component inventory into `dist/binary/`. |
| `e2e_packaged.sh` | Run `tests/e2e` against the built executable inside clean, offline Ubuntu 22.04 containers (no Python, no Tesseract). |
| `generate_inventory.py` | Generate the component inventory and collect license texts from the actual build environment (Python dists, Qt, Tesseract + linked native libraries via dpkg, language data). |
| `prepare_release.sh` | Collect the tested binary, inventory, wheel, sdist and license into a release folder with `SHA256SUMS` and generated release notes (no rebuild). |
| `docker_smoke.sh` | Build the CLI Docker image and smoke-test it offline on a synthetic folder (output, OCR words, unchanged original, exit code 3 for Ask). |
| `run_mutation.sh` | Run mutmut on the core modules and enforce the mutation-score threshold (default 95 %); report in `reports/mutation.txt`. |
| `mutation_score.py` | Compute the mutation score from `mutmut results`, excluding reviewed equivalents in `docs/mutation-equivalent.txt`. |
| `benchmark.py` | Reproducible sequential/fixed/auto OCR benchmark on a synthetic corpus; records platform, versions, wall time, medians, peak memory. |
| `screenshot.py` | Capture real screenshots of the running UI (real OCR batch) into `docs/media/`. |
| `audit_dependencies.sh` | Audit the locked runtime dependencies for known vulnerabilities with pip-audit. |
| `generate_samples.py` | Write a synthetic manual-test corpus (nested umlaut folders, scans, digital, mixed, encrypted, signed, corrupt, naturally suffixed). |
