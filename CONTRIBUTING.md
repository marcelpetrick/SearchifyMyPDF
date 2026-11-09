# Contributing

Read [`AGENTS.md`](AGENTS.md) (rules), [`PLAN.md`](PLAN.md) (status) and
[`docs/architecture.md`](docs/architecture.md) first.

## Setup

```bash
# Linux with uv (https://docs.astral.sh/uv/) and Tesseract (e.g. apt install tesseract-ocr)
uv sync --locked                 # exact, hash-locked dependencies incl. dev tools
scripts/fetch_tessdata.sh        # pinned eng/deu/osd language data → .cache/tessdata
uv run searchify-pdf             # start the app from source
```

## Before every commit

```bash
./localPipeline.sh               # full gate (needs Docker for binary, E2E and image)
./localPipeline.sh --fast        # quick inner loop
scripts/commit.sh patch "fix(scope): message"   # bump + gate + commit + push
```

Commits are atomic, use Conventional Commits, and bump the version (patch; minor for
features). Add tests for every behaviour change; keep statement and branch coverage ≥ 95 %.
Never commit personal documents — use `tests/synthetic.py`.
