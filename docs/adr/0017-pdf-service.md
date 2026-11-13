# 0017 — Parse PDFs only in a sandboxed service process

- Status: accepted
- Date: 2026-11-13

## Context

ADR 0016 sandboxed the OCR worker, but the application itself still parsed every
document with native code: pikepdf/qpdf to inspect, decrypt, mark, validate and
re-encrypt, and PDFium to find pages with text and to render pages for the text check
(#6). Those parsers see the same untrusted input as the worker. An exploit there ran
with the application's full rights (all files, network), and a parser crash took the
whole GUI down (#13).

Options considered:

- **Sandbox the application:** impossible without breaking it. It must write next to
  any source the user picks and may reach the network for the user-triggered update
  check.
- **One sandboxed process per operation:** the read restriction could then name each
  file, but discovery and validation would start dozens of processes per document.
- **One long-lived service that gets documents as bytes:** the service needs no access
  to user files at all, so the sandbox can be strict once and for good, and starting it
  costs only once per run.

## Decision

`engines/pdf_service.py` starts one service process on first use
(`python -m searchify_pdf.engines.pdf_service`, or `searchify-pdf --searchify-pdf-service`
in the frozen app). Before it reads its first request, it loads its parsers and then
sandboxes itself with the ADR 0016 layers:

- **Writes:** none, except its private temporary folder, which the client creates and
  removes.
- **Reads:** only the runtime (`runtime_read_dirs`). No user document is readable by
  path.
- **Network:** none.

On macOS the Seatbelt layer applies the same limits. On Windows the Low-integrity layer
blocks writes only (ADR 0016).

The application reads a file, sends its bytes with the request, and writes any document
that comes back (`pdf_inspect` keeps its path-based API). The operations, in
`engines/pdf_ops.py`, never touch the file system.

The protocol is a JSON header plus length-prefixed byte blobs over stdin/stdout. The
client treats answers as untrusted: sizes are bounded, types are checked, nothing is
unpickled. The service writes its answers to a private duplicate of stdout, so stray
output from a library can't corrupt the protocol.

Requests are serialized, as the in-process locks did before. A request that takes
longer than 300 s, or a service that crashes, fails that one document (`timeout` /
`invalid_pdf`). The next request starts a fresh service. Passwords travel only over
the pipe.

## Consequences

- A parser exploit in inspection, validation, text check or re-encryption can't read
  or change the user's files and can't use the network. A parser crash now fails one
  document instead of closing the application.
- The application holds each document in memory while it is sent, and the service
  holds its copy. That's fine for scanned documents, but very large PDFs use twice their
  size in RAM.
- Discovery reads every candidate file completely to check the output marker.
- Tests of the operations themselves can run them in-process (`pdf_inspect.InProcess`).
  Everything else goes through the real service, which is measured by coverage like
  the worker.
