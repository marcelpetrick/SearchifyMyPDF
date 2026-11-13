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
   link) is denied except beneath the worker's private temporary folder (plus
   `/dev/null`, which helper processes open read-write). The engine creates that folder
   per document, passes it as `TMPDIR` and removes it afterwards, even after a kill.
   The output is opened *before* the sandbox applies, and OCRmyPDF writes through
   that handle, so the destination folder and the output path need no grant at all
   (since 0.27.0).
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
worker logs one line saying what is active. `SEARCHIFY_PDF_SANDBOX=off`
turns it off for troubleshooting; `SEARCHIFY_PDF_SANDBOX=allow-reads` keeps everything
but the read restriction, for installations with runtime files in unusual places. When coverage.py measures a worker (test suite only;
it isn't shipped), its data folder is also writable.

### macOS and Windows (since 0.27.0)

The same `sandbox.apply` call has a layer for each platform:

- **macOS: a Seatbelt profile** (`sandbox_init`, `sandbox_darwin.py`). It is inherited
  and can't be lifted. On top of `(allow default)` it denies:
  - every write except the writable folders and files;
  - IP networking (outbound, inbound, bind);
  - reading file *contents* where user data lives (`/Users`, `/Volumes`, `/Network`,
    the temporary folders), except the runtime folders, the executable and the named
    files. Metadata stays readable, so path lookups work.
- **Windows: Low integrity** (`sandbox_windows.py`). The writable folders (inheritably)
  and files get a Low mandatory label first. Then the process lowers its own token to
  Low, which it can't raise again and Tesseract inherits. Windows then refuses writes
  to everything the user owns. Low integrity doesn't restrict reading or networking.
  AppContainer would, but every runtime file would need an ACL grant, which a portable,
  unpackaged program can't set up reliably. If a label can't be set, the token isn't
  lowered. The output is written through a handle opened at Medium integrity
  before lowering, so it never carries a Low label and the destination folder needs
  none.

## Consequences

- A compromised parser can't modify, encrypt, delete or read the user's other files,
  and it can't send anything over the network. It can read the runtime folders and
  the one source document.
- The main process no longer parses PDFs: inspection, validation, rendering and
  re-encryption run in the sandboxed PDF service (ADR 0017, since 0.26.0).
- Tests drive the logic against a fake libc and check the real kernel restrictions
  in a child process (`tests/unit/test_sandbox.py`); all OCR integration tests and the
  packaged end-to-end tests run with the sandbox on.
