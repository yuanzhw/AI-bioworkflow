## Summary

<!-- What problem does this pull request solve, and why is the change needed? -->

## Scope

- [ ] Bug fix
- [ ] Compiler or Workflow IR
- [ ] Recipe or Tool Catalog
- [ ] API or Web
- [ ] Execution backend or container
- [ ] Tests or documentation
- [ ] Other

## Architecture impact

<!-- Describe affected boundaries, or write "None". Check only applicable items. -->

- [ ] Natural-language processing still stops at Recipe Tool Plan.
- [ ] Final WDL is produced only by the deterministic Renderer.
- [ ] `workflow.steps` remains the canonical DAG; `workflow.calls` is compatibility-only.
- [ ] Catalog tool, command, and runtime definitions remain explicit and validated.
- [ ] Analyzer, Renderer, Checker, and `src.execution` boundaries are preserved.
- [ ] Not applicable to this change.

## Validation

<!-- Check only commands that were actually run and add concise results below. -->

- [ ] Python unit tests
- [ ] `scripts/check_p0.ps1`
- [ ] Representative WDL compile and syntax validation
- [ ] Frontend lint
- [ ] Frontend Catalog retrieval tests
- [ ] Frontend workflow graph tests
- [ ] Frontend production build
- [ ] Container build or smoke test
- [ ] Real execution test — explicit opt-in
- [ ] Documentation-only change

Commands and results:

```text

```

Skipped checks and reasons:

```text

```

## Documentation and contracts

- [ ] `docs/workflow-ir.md` was updated, or no IR/backend contract changed.
- [ ] `docs/test-cases.md` was updated, or no test input, expectation, or coverage intent changed.
- [ ] New tools or wrappers include schemas, command/runtime definitions, verification status, and appropriate tests.
- [ ] New dependencies are justified and lockfiles are updated.
- [ ] No secrets, credentials, private data, or local `.env` files are included.

## Evidence

<!-- Add screenshots for UI changes and representative diagnostics or WDL excerpts where useful. -->

## Risks and follow-ups

<!-- Note compatibility risks, known limitations, rollout concerns, or write "None". -->
