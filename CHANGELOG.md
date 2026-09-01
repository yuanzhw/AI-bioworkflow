# Changelog

All notable changes to AI-bioworkflow are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/) with pre-release identifiers while the public contracts are still evolving.

## [Unreleased]

## [0.1.0-alpha.2] - 2026-09-02

### Added

- A required `CI gate` that aggregates the complete Python suite, WOMtool validation, miniwdl production compatibility, and Web lint/tests/build.
- Baseline OSS governance through contribution, conduct, security, and maintainer policies plus a pull-request template.
- Bilingual public project entry points, a traceable RNA-seq case study, support guidance, and this changelog.

### Changed

- Upgraded the canonical CI validator to WOMtool 92, pinned by release version, byte size, and SHA-256, to align validation with the Cromwell 92 runner.
- Pinned third-party GitHub Actions to full commit SHAs and made the stable aggregate check mandatory for `main`.
- Reorganized the public README around product value, evidence, reproducibility, boundaries, and contribution paths; detailed internal milestone records remain in `DEVELOPMENT.md` and `docs/`.

## [0.1.0-alpha.1] - 2026-09-01

First public engineering preview.

### Added

- Catalog-constrained Recipe Tool Plans for RNA-seq differential expression, RNA-seq reference preparation, and compile-ready ChIP-seq peak calling.
- Canonical Workflow IR with scatter-aware DAG semantics, static analysis, deterministic repair, and deterministic WDL 1.0 rendering.
- An optional bounded Reviewer path restricted to policy-checked Workflow IR patches followed by full recompilation and validation.
- A shared application service exposed through the CLI and FastAPI, with SQLite run records, SSE events, named artifacts, diagnostics, and failure replay.
- A Next.js workbench with stable examples, run history, Workflow IR DAG inspection, and a Catalog browser.
- Execution-backend interfaces, Cromwell client contract tests, an explicit opt-in tiny RNA-seq E2E path, and recorded execution evidence.
- Public single-host deployment definitions, operational documentation, screenshots, and an online demo.

### Validation note

The `v0.1.0-alpha.1` snapshot used WOMtool 91 in its documented local installation path. The WOMtool 92 required gate was introduced in `v0.1.0-alpha.2`; the historical release record has not been rewritten.

[Unreleased]: https://github.com/yuanzhw/AI-bioworkflow/compare/v0.1.0-alpha.2...HEAD
[0.1.0-alpha.2]: https://github.com/yuanzhw/AI-bioworkflow/compare/v0.1.0-alpha.1...v0.1.0-alpha.2
[0.1.0-alpha.1]: https://github.com/yuanzhw/AI-bioworkflow/releases/tag/v0.1.0-alpha.1
