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
| `build_native_binary.sh` | Build and smoke-test the one-file executable on a Windows or macOS runner (Tesseract from Chocolatey/Homebrew, tessdata pinned, inventory, PyInstaller, then version/licenses/GUI drop/CLI OCR with the system Tesseract hidden). Used by `native.yml`. |
| `verify_release.sh` | Download a GitHub release (drafts too, with a write token), check `SHA256SUMS`, require Linux, Windows and macOS executables and run the Linux one. Used by `release.yml`. |
| `prepare_release.sh` | Collect the tested executables of all platforms present in `dist/binary` (Linux required; Windows/macOS from the native builds), inventories, wheel, sdist and license into a release folder with `SHA256SUMS` and generated release notes (no rebuild). |
| `docker_smoke.sh` | Build the CLI Docker image and smoke-test it offline on a synthetic folder (output, OCR words, unchanged original, exit code 3 for Ask). |
| `run_mutation.sh` | Run mutmut on the core modules and enforce the mutation-score threshold (default 95 %); report in `reports/mutation.txt`. |
| `mutation_score.py` | Compute the mutation score from `mutmut results`, excluding reviewed equivalents in `docs/mutation-equivalent.txt`. |
| `benchmark.py` | Reproducible sequential/fixed/auto OCR benchmark on a synthetic corpus; records platform, versions, wall time, medians, peak memory. |
| `screenshot.py` | Capture real screenshots of the running UI (real OCR batch) into `docs/media/`. |
| `audit_dependencies.sh` | Audit the locked runtime dependencies for known vulnerabilities with pip-audit. |
| `generate_samples.py` | Write a synthetic manual-test corpus (nested umlaut folders, scans, eight scanner defects — skew, noise, blur, low contrast, low resolution, landscape, two columns, upside down —, a 40-page report, digital, mixed, encrypted, owner-restricted, signed, corrupt, naturally suffixed). |
| `check_binary_size.py` | Report what the one-file executable contains (largest entries and packages) and fail above the size budget (95 MB); pipeline stage `size`. |
| `../packaging/linux/build_icu_data.sh` | Rebuild Qt's ICU 73.2 data trimmed to the en/de UI (`icu-data-filter.json`); runs in the builder image. |
