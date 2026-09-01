# Contributing to AI-bioworkflow

Thank you for helping improve AI-bioworkflow. The project is an open-source
bioinformatics workflow compiler: natural-language requests are constrained to
a Catalog-bound Recipe Tool Plan, normalized into Workflow IR, and rendered as
validated WDL 1.0 by deterministic code.

Contributions should keep this path auditable, reproducible, and testable.

## Before you start

- Search existing issues and pull requests before opening a new one.
- Small bug fixes, tests, and documentation improvements may go directly to a
  pull request.
- Open an issue before making a substantial change to Workflow IR semantics,
  public APIs, dependencies, recipes, tools, containers, execution backends, or
  renderer behavior.
- Keep each pull request focused on one problem. Roadmap entries are not an
  automatic approval to implement the full feature.

Read these sources of truth before changing the corresponding area:

- [DEVELOPMENT.md](./DEVELOPMENT.md) for architecture and roadmap decisions.
- [Workflow IR specification](./docs/workflow-ir.md) before changing schemas,
  expressions, Analyzer/Repairer behavior, renderers, Catalog resolution, or
  backend mapping.
- [Test cases](./docs/test-cases.md) before changing fixtures, expected output,
  or coverage intent. Update it when those contracts change.

## Development setup

The project targets Python 3.13+ and uses `uv` with the repository `.venv`.
Java 17+ and WOMtool 92 are used for the canonical WDL validation path.
miniwdl is a secondary compatibility check for the production API image.

```powershell
git clone https://github.com/yuanzhw/AI-bioworkflow.git
cd AI-bioworkflow
uv sync

# Complete Python suite plus representative WDL compilation and validation
powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1
```

For the Web application:

```powershell
cd web
npm ci
npm run lint
npm run test:catalog-retrieval
npm run test:graph
npm run build
```

On POSIX systems, run the Python suite with:

```bash
./.venv/bin/python -m unittest discover -v
```

Structured compilation through `--input` does not require an API key. Natural-
language planning requires `DEEPSEEK_API_KEY`. Never commit `.env` files, API
keys, credential paths, patient or controlled-access data, or private runtime
logs.

## Architecture boundaries

Every contribution must preserve these invariants:

- Natural-language input becomes a Recipe Tool Plan before Workflow IR. A
  model must not generate final WDL directly.
- Recipes and tools are admitted through the formal Catalog. The compiler must
  not infer, search for, or silently replace container images.
- `workflow.steps` is the canonical DAG. `workflow.calls` is a generated
  compatibility view for older flat inputs.
- Workflow IR is validated before deterministic rendering, and generated WDL
  is checked before it is treated as successful output.
- Reviewer repair may propose only policy-constrained Workflow IR patches. It
  may not modify Catalog definitions, command templates, runtime images, or
  final WDL, and every accepted patch must pass the complete compiler chain.
- Execution goes through `src.execution`. The default backend remains disabled,
  and real execution tests stay explicitly opt-in.
- CLI stdout remains machine-consumable WDL or JSON. Logs and diagnostics go to
  stderr.
- API and Web layers reuse the application service; they do not duplicate
  planning, Catalog resolution, or WDL generation logic.

## Change-specific requirements

### Workflow IR, Analyzer, Repairer, or Renderer

- Add focused tests for the new or changed contract.
- Update `docs/workflow-ir.md` when semantics or backend mapping changes.
- Generate representative WDL and validate it with WOMtool 92.
- Run `miniwdl check` as the secondary production-compatibility check.

### Recipe or Tool Catalog

- Define explicit input, output, parameter, command, version, and runtime
  schemas.
- Set an honest `execution_verification` state and provide evidence when the
  state is `smoke-tested` or `e2e-validated`.
- Add resolver, rendering, validation, and retrieval coverage as applicable.
- Do not use an unpinned or silently discovered container image.

### Project-maintained container or wrapper

- Include a description, schemas, command example, explicit runtime reference,
  Dockerfile, packaged helper scripts, `image_revision.txt`, and
  `smoke_test.sh`.
- Add minimal build and execution-path coverage.

### Execution backend

- Implement the `src.execution` interfaces.
- Cover availability, submission, polling, outputs, metadata, and failure
  semantics.
- Explain any real execution verification that could not be run.

### Frontend or API

- Preserve the published API and artifact contracts, or document the change.
- Run the relevant frontend checks listed above.
- Include screenshots for visible UI changes.

### Dependencies

Explain why the dependency is required and update the appropriate lockfile.
Avoid adding a dependency when the existing standard library or project
tooling is sufficient.

## Pull requests

A pull request should include:

- the problem and motivation;
- the implemented scope and affected architecture boundaries;
- commands run and their results;
- skipped checks and the reason;
- compatibility, deployment, or security risks;
- documentation changes and useful screenshots or artifacts.

Use a concise, imperative, maintainer-authored title. Branch names, commit
messages, pull request text, and public documentation must not contain tool
signatures, autogenerated-by lines, assistant branding, or unrelated PR-number
suffixes.

All required checks should pass before merge. Squash merges should use a clean
subject without an automatic `(#PR_NUMBER)` suffix.

The required GitHub check is `CI gate`. It aggregates the complete Python
suite with WOMtool validation, production miniwdl compatibility, and Web
lint/tests/build. The workflow and local equivalents are documented in
[CI and merge gate](./docs/ci.md). Do not bypass or rename this check without
updating the `Mainline Safeguard` ruleset in the same maintenance change.

## Security reports

Do not open a public issue for a suspected vulnerability. Follow
[SECURITY.md](./SECURITY.md) instead.

## License

By contributing, you agree that your contribution may be distributed under the
repository's [Apache License 2.0](./LICENSE).
