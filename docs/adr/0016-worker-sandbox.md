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
   `TMPDIR` and removes it afterwards, even after a kill. Reading isn't
   restricted: the interpreter, the bundled libraries and the language data live in
   too many places to list reliably.
3. **Landlock, network (ABI ≥ 4, Linux 6.7):** no TCP connect or bind.
4. **seccomp:** `socket()` only for `AF_UNIX`, no `io_uring_setup`, and foreign
   syscall ABIs (i386 `int 0x80`, x32) refused. This closes UDP/raw sockets and works
   on older kernels without Landlock networking.

The sandbox is best effort. Layers the kernel doesn't support are skipped, and the
worker logs one line saying what is active. It is Linux-only for now; Windows (AppContainer /
job objects) and macOS (sandbox profiles) stay open in #13. `SEARCHIFY_PDF_SANDBOX=off`
turns it off for troubleshooting. When coverage.py measures a worker (test suite only;
it isn't shipped), its data folder is also writable.

## Consequences

- A compromised parser can still **read** the user's files, but it can't modify,
  encrypt or delete them, and it can't send them over the network.
- The main process still parses PDFs (pikepdf/PDFium for inspection, validation and
  re-encryption) outside the sandbox. Moving those into the worker is a later step.
- Tests drive the logic against a fake libc and check the real kernel restrictions
  in a child process (`tests/unit/test_sandbox.py`); all OCR integration tests and the
  packaged end-to-end tests run with the sandbox on.
