# AGENTS.md

## Project Overview

This project converts natural-language bioinformatics requests into structured
Recipe Tool Plans, normalizes them into Workflow IR, and deterministically
compiles validated IR into WDL 1.0.

The LLM must not directly generate final WDL. It may assist with planning,
review, or bounded IR repair only through explicit structured interfaces.

## Sources Of Truth

- Read `DEVELOPMENT.md` for architecture boundaries and roadmap decisions.
- Read `docs/workflow-ir.md` before modifying IR schemas, analyzers,
  repairers, renderers, recipe resolution, or backend behavior.
- Treat `workflow.steps` as the canonical workflow DAG representation.
  `workflow.calls` exists for compatibility with older flat-call inputs.

## Architecture Rules

- Natural-language input is converted into a `Recipe Tool Plan` before it
  becomes Workflow IR.
- Recipe and tool choices must be validated through the formal Catalog.
- Workflow IR must be validated before WDL generation.
- WDL generation must remain deterministic Python/template code.
- Do not bypass Analyzer, Renderer, or Checker validation boundaries.
- Prefer explicit schemas, recorded provenance, and tests over behavior hidden
  in prompts.

## Tool And Container Rules

- Formal tool definitions belong in the Tool Catalog and must define explicit
  input, output, parameter, command, and runtime schemas.
- The compiler must not search for, infer, or silently replace container images.
- Existing workflows must use the image declared by the Tool Catalog.
- When adding a new common tool, a trusted public image may be evaluated before
  being explicitly admitted to the Catalog.
- Project-maintained R/Python/helper wrappers must include:
  - description
  - input and output schema
  - command template or example command
  - explicit runtime/container reference
  - Dockerfile and packaged helper scripts when applicable
  - `smoke_test.sh` for project-maintained containers
  - minimal resolver, rendering, or execution-path test coverage

## Development Commands

- Run unit tests with:
  `.venv/bin/python -m unittest discover -v`
- When a change affects generated WDL, recipes, renderers, or validation paths,
  generate representative WDL and run:
  `miniwdl check path/to/generated.wdl`
- Do not skip relevant verification unless the user explicitly asks, or clearly
  explain why it could not be run.

## Do Not

- Do not bypass the Recipe Tool Plan / Workflow IR boundary.
- Do not let an LLM directly produce final WDL in the main execution path.
- Do not introduce a new dependency without explaining why.
- Do not rewrite the architecture for a narrowly scoped bugfix.
- Do not assume local bioinformatics tools are installed; prefer containerized
  execution through approved runtime definitions.
- Do not implement roadmap-only Agent behavior unless the task explicitly calls
  for it.

## Definition Of Done

A change is complete only when:

- Relevant tests pass or the reason they cannot be run is explained.
- Generated WDL is syntactically validated when the change affects WDL output.
- Any new tool or wrapper has schema, runtime, example, and appropriate test
  coverage.
- Container changes include smoke tests when applicable.
- Documentation is updated when architecture or IR contracts change.
- The final response summarizes changed files and verification steps.
