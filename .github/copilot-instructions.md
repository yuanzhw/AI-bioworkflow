# Copilot instructions for AI-bioworkflow

## What this repository is

- AI-bioworkflow is a bioinformatics workflow compiler: natural-language requests are first converted into a **Recipe Tool Plan**, then normalized into **Workflow IR**, then deterministically rendered to **WDL 1.0**.
- The LLM must **not** generate final WDL directly in the main path. WDL output must come from Python renderer/template code.
- This repo is also a public portfolio/demo project, so keep public-facing text professional and maintainer-authored.

## Read these first

1. `README.md` for entrypoints and local commands.
2. `DEVELOPMENT.md` for architecture boundaries and directory map.
3. `docs/workflow-ir.md` before changing IR/schema/analyzer/repairer/renderer/catalog/backend behavior.
4. `docs/test-cases.md` before changing tests; update it when test inputs, expected outputs, or coverage intent change.

## Core architecture rules

- Treat `workflow.steps` as the canonical workflow DAG. `workflow.calls` exists for compatibility with older flat-call inputs.
- Natural language only goes to `src/nl_planner.py` and should stop at Recipe Tool Plan.
- Structured compilation flows through the compiler graph in `src/graph.py`: normalizer -> analyzer -> renderer -> checker, with bounded repair.
- Do not bypass Analyzer, Renderer, Checker, or execution backend interfaces.
- Tool/runtime definitions belong in the catalog; do not guess or auto-discover container images.
- Catalog tools must explicitly declare `runtime.docker`.
- WDL execution behavior must go through `src.execution`; the default backend is intentionally disabled.

## High-value repo map

- `main.py`: CLI entrypoint for natural-language planning and structured compile mode.
- `src/services/`: reusable application services shared by CLI and API.
- `src/api/`: FastAPI app, DTOs, routes, run persistence/event streaming.
- `src/catalog/` + `src/recipes/`: approved tools and recipe definitions.
- `src/renderers/wdl.py`: deterministic Workflow IR -> WDL renderer.
- `tests/`: unit/integration coverage, plus optional tiny-run/e2e paths.
- `containers/<tool>/<version>/`: project-maintained container definitions and smoke tests.

## Working rules for common changes

- If you change IR structure, expressions, scatter semantics, catalog resolution, analyzer behavior, repair logic, or WDL rendering:
  - update code,
  - update `docs/workflow-ir.md`,
  - update/add tests.
- If you change tests or test coverage intent, update `docs/test-cases.md`.
- If you add or modify a project-maintained tool/container, include schema/runtime details, Docker assets, `smoke_test.sh`, and focused resolver/render/execution-path coverage.
- Keep CLI artifact output machine-consumable on stdout; logs and diagnostics belong on stderr.

## Verification commands

- Main unit test command:
  - `.venv/bin/python -m unittest discover -v`
- Representative structured compile:
  - `.venv/bin/python main.py --input examples/rnaseq_deg_recipe_plan.json --output /tmp/rnaseq_deg.wdl`
- FastAPI dev server:
  - `.venv/bin/python -m src.api.server`
- Local Windows-oriented P0 wrapper:
  - `powershell -ExecutionPolicy Bypass -File scripts/check_p0.ps1`
- Real Cromwell tiny e2e is opt-in only through `scripts/check_p0.ps1 -RunE2E`.
- If a change affects generated WDL, recipes, renderers, or validation paths, also run `miniwdl check` on a representative generated WDL when `miniwdl` is available.

## Environment/setup notes for cloud agents

- The project targets Python 3.13+ and prefers `uv` / the repo `.venv`.
- In this repository, a fresh cloud workspace may not have `uv` installed and may not have a pre-created `.venv`.
- If `uv` is missing or `.venv` does not exist, create a venv and install the repo in editable mode:
  - `python3 -m venv .venv`
  - `.venv/bin/pip install --upgrade pip`
  - `.venv/bin/pip install -e . --ignore-requires-python`
  - use `--ignore-requires-python` only as a cloud-workspace fallback when the agent image provides Python 3.12 but not Python 3.13 yet
- If you need the FastAPI server tests or local WDL validation in that fallback setup, also install:
  - `.venv/bin/pip install uvicorn miniwdl`
- This fallback is useful when the cloud image only has Python 3.12.
- Without those installs, imports such as `dotenv`, `pydantic`, `fastapi`, and `uvicorn` will fail and tests/CLI will not start.
- Without `miniwdl` or WOMtool/Java, WDL validation will report that no validator is available.

## Natural-language planning notes

- Natural-language planning requires `DEEPSEEK_API_KEY`.
- Deterministic structured compilation via `--input` should work without any API key.
- When debugging planner behavior, prefer saving the planner prompt/plan rather than bypassing the plan -> IR boundary.

## Avoid these mistakes

- Do not let an LLM directly emit final WDL for production code paths.
- Do not implement new behavior only in `workflow.calls` while forgetting `workflow.steps`.
- Do not silently introduce new tools, containers, or runtime images outside the formal catalog.
- Do not assume local bioinformatics tools are installed; prefer approved containerized execution paths.
- Do not treat roadmap text in `DEVELOPMENT.md` as already-implemented behavior.
