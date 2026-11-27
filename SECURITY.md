# Security policy

Searchify PDF processes untrusted PDFs locally with native parsers (Tesseract, Leptonica,
QPDF, PDFium). The OCR worker and PDF service apply platform-specific sandboxing.
Linux and macOS restrict file access and networking. Windows Low integrity limits
writes. See [`docs/security-review.md`](docs/security-review.md) for the platform
limits and residual risks.

## Reporting a vulnerability

Please report privately via GitHub's **Report a vulnerability** (Security tab →
Advisories) for `marcelpetrick/SearchifyMyPDF`. Include the version (`searchify-pdf
--version`), platform and, if possible, a synthetic reproducer. Do not attach personal
documents.

## Supported versions

Fixes are shipped in new releases while the project is in 0.x. Use the
[latest stable release](https://github.com/marcelpetrick/SearchifyMyPDF/releases/latest).
