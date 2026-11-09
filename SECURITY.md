# Security policy

Searchify PDF processes untrusted PDFs locally with native parsers (Tesseract, Leptonica,
QPDF, PDFium). It is not a sandbox. See [`docs/security-review.md`](docs/security-review.md).

## Reporting a vulnerability

Please report privately via GitHub's **Report a vulnerability** (Security tab →
Advisories) for `marcelpetrick/SearchifyMyPDF`. Include the version (`searchify-pdf
--version`), platform and, if possible, a synthetic reproducer. Do not attach personal
documents.

## Supported versions

Only the latest prerelease receives fixes while the project is in 0.x.
