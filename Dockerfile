# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marcel Petrick <mail@marcelpetrick.it>
#
# Headless Searchify PDF (CLI) image.
#   docker run --rm -v "$PWD:/data" ghcr.io/marcelpetrick/searchifymypdf /data
# Searchable copies are written next to each PDF below /data. Settings (optional) are
# read from /config/searchify-pdf.settings.json.

FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM python:3.12-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv export --locked --no-dev --no-emit-project --format requirements-txt -o requirements.txt \
    && uv build --wheel --out-dir /build/dist

FROM python:3.12-slim-bookworm
ARG VERSION=dev
LABEL org.opencontainers.image.title="Searchify PDF" \
      org.opencontainers.image.description="Make scanned PDFs searchable (headless CLI)" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/marcelpetrick/SearchifyMyPDF" \
      org.opencontainers.image.version="${VERSION}"
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /build/requirements.txt /build/dist/*.whl /tmp/pkg/
RUN pip install --no-cache-dir --require-hashes -r /tmp/pkg/requirements.txt \
    && pip install --no-cache-dir --no-deps /tmp/pkg/*.whl \
    && rm -rf /tmp/pkg \
    && useradd --create-home --uid 1000 searchify \
    && mkdir -p /config /data && chown searchify /config
ENV SEARCHIFY_PDF_HOME=/config
USER searchify
WORKDIR /data
ENTRYPOINT ["searchify-pdf", "--cli", "--non-interactive"]
CMD ["--help"]
