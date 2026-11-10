# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/) and
[Conventional Commits](https://www.conventionalcommits.org/). Every commit bumps
the version (patch for ordinary changes, minor for major features).

<!-- entries -->

## 0.16.19 — 2026-11-10

- test(e2e): run real-life corpus, /config settings, docker stop and non-root checks against the Docker image

## 0.16.18 — 2026-11-10

- test(e2e): packaged binary converts the real-life corpus, cancels on docker stop and prompts on a terminal

## 0.16.17 — 2026-11-10

- test(fixtures): generate scanner-defect, long and owner-restricted synthetic PDFs with OCR tests

## 0.16.16 — 2026-11-10

- test(fixtures): add real-life public-domain and CC BY-SA scan corpus with workflow tests

## 0.16.15 — 2026-11-10

- docs(plan): plan more E2E coverage, real-life fixtures and a smaller executable

## 0.16.14 — 2026-11-10

- test(storage): cover staging leftovers that cannot be deleted

## 0.16.13 — 2026-11-10

- fix(storage): never break a live same-host lock and age out foreign locks after the max timeout

## 0.16.12 — 2026-11-10

- fix(cli): cancel headless runs cleanly on SIGINT and SIGTERM

## 0.16.11 — 2026-11-10

- fix(ui): record statistics according to the batch settings snapshot

## 0.16.10 — 2026-11-10

- fix(ui): keep paths added during a run queued and start open events afterwards

## 0.16.9 — 2026-11-10

- docs(plan): record milestone status and evidence for A01-A20

## 0.16.8 — 2026-11-10

- chore(scripts): add sample corpus generator and run mutation checks on core PRs

## 0.16.7 — 2026-11-10

- docs(readme): document usage, pipeline, Docker and add real UI screenshots

## 0.16.6 — 2026-11-10

- ci(deps): add Dependabot and daily pip-audit dependency scan

## 0.16.5 — 2026-11-10

- docs: add security review, compliance checklist, desktop matrix, Windows Search guide and benchmark baseline

## 0.16.4 — 2026-11-10

- docs(architecture): add C4 views, flow diagrams, pipeline overview and ADRs 0001-0009

## 0.16.3 — 2026-11-10

- fix(inventory): list only bundled runtime components and the PyInstaller bootloader

## 0.16.2 — 2026-11-10

- fix(ui): improve progress bar contrast and escape ampersand in group titles

## 0.16.1 — 2026-11-10

- fix(publisher): remove staging leftovers of interrupted runs and add fault tests

## 0.16.0 — 2026-11-10

- test(mutation): add mutmut baseline, hardening tests, threshold and scheduled workflow

## 0.15.0 — 2026-11-10

- build(docker): add headless CLI image with smoke test and GHCR publishing workflow

## 0.14.0 — 2026-11-10

- ci(release): add tag-triggered release pipeline promoting tested assets to a draft release

## 0.13.0 — 2026-11-10

- build(linux): add self-contained PyInstaller executable with bundled Tesseract and packaged E2E tests

## 0.12.1 — 2026-11-09

- fix(engine): run OCRmyPDF page workers as threads for frozen-app safety

## 0.12.0 — 2026-11-09

- feat(cli): add entry point with drop-launch dispatch, headless CLI and exit codes

## 0.11.0 — 2026-11-09

- feat(ui): add Qt desktop UI with drop zone, progress, prompts, settings, statistics and about

## 0.10.0 — 2026-11-09

- feat(platform): add bundled runtime setup, Linux launcher integration and component inventory

## 0.9.0 — 2026-11-09

- feat(statistics): add opt-in local statistics with true medians and labelled estimates

## 0.8.0 — 2026-11-09

- feat(i18n): add English and German catalogs for outcomes, reasons, UI and prompts

## 0.7.0 — 2026-11-09

- feat(workflow): add batch workflow with policy decisions, prompts, locking and cancellation

## 0.6.0 — 2026-11-09

- feat(publisher): add validated staging publication and shared CPU budget scheduler

## 0.5.0 — 2026-11-09

- feat(engine): add OCRmyPDF adapter running isolated, cancellable worker processes

## 0.4.0 — 2026-11-09

- feat(discovery): add PDF inspection and recursive discovery with generated-copy exclusion

## 0.3.0 — 2026-11-09

- feat(storage): add portable settings repository, atomic writes and stale-safe locks

## 0.2.0 — 2026-11-09

- feat(domain): add validated settings, policies, path rules and job outcomes

## 0.1.2 — 2026-11-09

- chore: log every commit step in PLAN.md via commit helper

## 0.1.1 — 2026-11-09

- ci: run localPipeline.sh in GitHub Actions on Python 3.12 and 3.13

## 0.1.0 — 2026-11-09

- chore: project scaffold (GPLv3, packaging metadata, AGENTS.md, PLAN.md, version tooling)
