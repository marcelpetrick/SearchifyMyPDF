# Red-team review of the first working prototype (VISION §11, A20)

Date: 2026-11-10 · Scope: version 0.16.x, Linux executable, CLI and Docker image.
A packaged local PDF parser is **not** a security sandbox: OCRmyPDF, pikepdf/QPDF, PDFium,
Leptonica and Tesseract parse untrusted input with the user's privileges.

| # | Area | Finding / threat | Mitigation | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Overwrites | A crafted name could make the copy path equal the original or a hard link to it | Alias checks (same inode, case-insensitive equality), symlink destinations rejected | `test_destination_problem`, `test_destination_symlink_rejected` |
| 2 | Overwrites | Two instances writing the same copy | Per-target `O_EXCL` lock, stale recovery by atomic rename, no-clobber `link` | `test_simultaneous_instances_never_race_on_one_output` |
| 3 | Interruption | Kill during OCR leaves partial files | Hidden staging + validation; leftovers removed under lock on next run; previous copy untouched | `test_hard_kill_during_ocr_then_recovery`, `test_overwrite_failure_keeps_previous_output` |
| 4 | Traversal | Symlink loops / links to elsewhere in folders | Directory symlinks never followed, symlinked files skipped and reported | `test_symlinks_not_followed_in_folders` |
| 5 | Resource exhaustion | Huge pages / endless OCR | Per-document timeout kills the whole process group; bounded workers/queue; memory-aware Auto | `test_engine_timeout_kills_tesseract`, `test_unusually_large_page`, `test_worker_limit_is_respected_and_timed` |
| 6 | Subprocess boundary | Shell injection via file names | Argument arrays only, JSON request to the worker, no shell | code review, `test_malformed_launch_arguments` |
| 7 | Frozen relaunch | Worker could relaunch the GUI | Worker flag handled before UI import; page workers are threads | `test_entry_point_dispatch`, packaged E2E |
| 8 | Settings corruption | Malformed/huge/hostile settings file | Size limit, strict schema, data-only JSON, defaults + backup, never executed | `test_malformed_file_recovers_with_backup`, `test_oversized_file_is_malformed` |
| 9 | Protected documents | Signatures invalidated, encryption bypassed or weakened, passwords or decrypted content leaking | Signed PDFs rejected. Password PDFs only with the user's password; owner-restricted only when opted in (ADR 0011). Copies re-encrypted with the same password and permissions (AES-256, random owner password when unknown); decrypted data and text cross-check renderings (ADR 0013) only in a private 0700 temp folder, always removed; passwords memory-only, never in argv, settings, logs or `repr` | `test_protected_pdfs.py`, `test_real_restricted_scan_is_processed_when_enabled`, `test_protected_pdfs_with_password_file_and_restricted_opt_in`, `test_password_protected_source_is_checked_and_left_alone` |
| 10 | Privacy | Statistics leaking paths/content | Statistics opt-in, contain no paths or text | `test_json_roundtrip_has_no_paths_or_text` |
| 11 | Library path | Bundled `LD_LIBRARY_PATH` leaking into `xdg-open` | `external_env` restores the original path | `test_external_env_restores_library_path` |
| 12 | Supply chain | Tampered language data / actions / dependencies | SHA-256 pinned tessdata, `uv.lock` with hashes (`--require-hashes` in Docker), actions pinned to SHAs, Dependabot | `scripts/fetch_tessdata.sh`, workflows |
| 13 | Release tampering | Rebuilt or swapped binaries | Release promotes the exact tested artifact, verifies `SHA256SUMS`, draft for human review; Docker image with provenance + SBOM | `.github/workflows/release.yml`, `docker.yml` |
| 14 | Docker | Container running as root on host files | Runs as uid 1000, no network needed (`--network none` in smoke test) | `scripts/docker_smoke.sh` |
| 15 | Update check | Unwanted network traffic, spoofed answer, opening a hostile URL | Only on explicit request; one GET with a generic client name; TLS verified against the OS store; answer size-capped and schema-checked; pre-releases ignored; only this project's release URLs (https) are opened; nothing downloaded (ADR 0014) | `test_updates.py`, `test_open_url`, `test_check_for_updates`, native smoke step 6 |
| 16 | Native parser exploit | A crafted PDF/image takes over qpdf, Leptonica or Tesseract in the worker and damages or sends away the user's files | On Linux the worker sandboxes itself before parsing (ADR 0016): Landlock allows writes only to its private temp folder and the output file and reads only of the runtime (system folders, Python, Tesseract, language data) and the source, no TCP; seccomp allows only `AF_UNIX` sockets and no io_uring; inherited by Tesseract. Windows/macOS not yet | `test_sandbox.py` (real kernel check in a child), all OCR integration tests run sandboxed |

Residual risks (tracked as issues): memory-safety bugs in native parsers. The Linux worker
is sandboxed (row 16, ADR 0016); the main process and the Windows/macOS workers are not
sandboxed yet (#13). No binary signing
yet (#12).
