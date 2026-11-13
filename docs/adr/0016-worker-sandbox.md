# 0016 — Sandbox the OCR worker on Linux (Landlock + seccomp)

- Status: accepted
- Date: 2026-11-12

## Context

The worker process (ADR 0003) hands untrusted PDFs and page images to native parsers:
qpdf (pikepdf), Leptonica, Tesseract. A memory-safety bug in one of them runs attacker
code with the user's privileges: it could encrypt or delete the user's documents or
send them away. The security review (A20, row 16) tracked this as residual risk #13.

Options considered:

- **bubblewrap/firejail:** not installed everywhere, can't be bundled cleanly, and
  unprivileged user namespaces are restricted on current Ubuntu (AppArmor). It would
  silently fail exactly where most users are.
- **A separate sandbox launcher:** more moving parts, and it would also need namespaces.
- **Self-applied Landlock + seccomp in the worker:** unprivileged and inherited by every
  child (Tesseract), with no extra binaries. Needs only `prctl(PR_SET_NO_NEW_PRIVS)`.

## Decision

Before parsing anything, the worker restricts itself (`engines/sandbox.py`):

1. `no_new_privs`, so the restrictions can't be shed through setuid binaries.
2. **Landlock, files:** every write right (write, truncate, create, remove, rename,
   link) is denied except beneath the worker's private temporary folder and on its
   one output file (plus `/dev/null`, which helper processes open read-write). The engine creates that folder per document, passes it as
   `TMPDIR` and removes it afterwards, even after a kill.
   **Reading** (since 0.25.0) is allowed only for the source file, those writable
   paths and the runtime (`runtime_read_dirs`): the system folders (`/usr`, `/lib*`,
   `/etc`, `/opt`, `/proc`, `/sys`, `/dev`, …), the Python installation and import path,
   the `PATH` and `LD_LIBRARY_PATH` entries (with their prefix, e.g. `/opt/brew`), the
   PyInstaller bundle and `TESSDATA_PREFIX`. A folder that is the home folder or
   contains it is never granted, so the working directory or `~/.local/bin`'s parent
   can't open the user's documents. `/proc` is safe to grant because Landlock forbids
   ptrace-style access (e.g. `/proc/<pid>/environ`) to processes outside the sandbox.
3. **Landlock, network (ABI ≥ 4, Linux 6.7):** no TCP connect or bind.
4. **seccomp:** `socket()` only for `AF_UNIX`, no `io_uring_setup`, and foreign
   syscall ABIs (i386 `int 0x80`, x32) refused. This closes UDP/raw sockets and works
   on older kernels without Landlock networking.

The sandbox is best effort. Layers the kernel doesn't support are skipped, and the
worker logs one line saying what is active. It is Linux-only for now; Windows (AppContainer /
job objects) and macOS (sandbox profiles) stay open in #13. `SEARCHIFY_PDF_SANDBOX=off`
turns it off for troubleshooting; `SEARCHIFY_PDF_SANDBOX=allow-reads` keeps everything
but the read restriction, for installations with runtime files in unusual places. When coverage.py measures a worker (test suite only;
it isn't shipped), its data folder is also writable.

## Consequences

- A compromised parser can't modify, encrypt, delete or read the user's other files,
  and it can't send anything over the network. It can read the runtime folders and
  the one source document.
- The main process no longer parses PDFs: inspection, validation, rendering and
  re-encryption run in the sandboxed PDF service (ADR 0017, since 0.26.0).
- Tests drive the logic against a fake libc and check the real kernel restrictions
  in a child process (`tests/unit/test_sandbox.py`); all OCR integration tests and the
  packaged end-to-end tests run with the sandbox on.
