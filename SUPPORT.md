# Support

AI-bioworkflow is an alpha open-source engineering preview maintained on a best-effort basis. Public, reproducible reports are welcome; the project does not provide an uptime, response-time, workflow-execution, or scientific-analysis service-level agreement.

## Where to ask

- **Reproducible bug, setup problem, or focused feature request:** search the [GitHub issues](https://github.com/yuanzhw/AI-bioworkflow/issues), then open a new issue if no existing report matches.
- **Contribution proposal:** follow [CONTRIBUTING.md](./CONTRIBUTING.md). Open an issue before substantial changes to public contracts, dependencies, recipes, tools, containers, execution backends, or renderer behavior.
- **Suspected vulnerability:** do **not** open a public issue. Use the private reporting route in [SECURITY.md](./SECURITY.md).

Questions and reports may be written in English or Chinese.

## What to include

A useful support report contains:

- the release tag or commit SHA;
- operating system, Python version, and installation method;
- whether the input used the natural-language or structured path;
- the configured `WDL_VALIDATOR` and its version;
- a minimal synthetic or public input that reproduces the problem;
- the exact command and complete redacted error or diagnostic;
- expected behavior and observed behavior;
- relevant screenshots for a Web issue, with secrets and private data removed.

For execution-backend problems, also include the selected backend, Cromwell version, workflow status, and sanitized backend response. State clearly whether real execution was explicitly enabled; a public-demo compilation is not a Cromwell execution.

## Before opening an issue

1. Check the [README](./README.en.md), [CI guide](./docs/ci.md), [deployment guide](./docs/deployment.md), and [known project boundaries](./DEVELOPMENT.md).
2. Reproduce through the structured example when possible:

   ```powershell
   uv run main.py --input examples/rnaseq_deg_recipe_plan.json --output .cache/support/rnaseq_deg.wdl
   ```

3. Run the relevant local checks from [CONTRIBUTING.md](./CONTRIBUTING.md) and report any check that could not run.
4. Reduce the report to synthetic data. Never upload patient data, controlled-access data, credentials, API keys, private container-registry paths, or unredacted runtime logs.

## Supported scope

Best-effort fixes target the latest `main` branch and current `0.1.x` pre-release line. Older snapshots, local forks, and modified deployments may still receive guidance, but are not maintained release lines.

Good public support topics include:

- installation and deterministic structured compilation;
- Recipe Tool Plan, Workflow IR, Analyzer, Renderer, or Checker behavior;
- Catalog schemas and resolver errors;
- API/Web artifacts, events, DAG display, and run-history behavior;
- documented CI, deployment, and opt-in execution-backend contracts;
- focused proposals for tests, recipes, tools, and documentation.

The following are outside the project's support commitment:

- choosing or approving a clinical or production research analysis;
- interpreting biological results or providing medical advice;
- processing private datasets on behalf of a reporter;
- guaranteeing that arbitrary third-party data, containers, or infrastructure will execute successfully;
- operating the public demo as a production workflow service;
- debugging undocumented modifications without a minimal reproduction.

WDL syntax/type validation is not a scientific review and does not establish real execution. See the [RNA-seq case study](./docs/rnaseq-case-study.md) for the evidence boundary used by this project.

## Community expectations

Keep reports focused, redact sensitive information, and follow the [Code of Conduct](./CODE_OF_CONDUCT.md). Maintainer decisions and the path for becoming a maintainer are documented in [MAINTAINERS.md](./MAINTAINERS.md).
