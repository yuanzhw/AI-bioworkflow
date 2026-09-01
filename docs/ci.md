# Continuous integration and merge gate

Every pull request targeting `main` must produce the stable `CI gate` check.
The workflow intentionally has no path filter: documentation-only changes must
report the same required check as compiler, API, Web, and deployment changes.

## Required check topology

`CI gate` aggregates three independent jobs:

1. **Python tests and WOMtool validation**
   - Python 3.13 and the locked `uv` environment.
   - The complete `unittest` suite.
   - Container build-script compilation and a dry run of every maintained
     container definition.
   - Deterministic compilation of representative Recipe Tool Plans and
     Workflow IR followed by WOMtool validation.
2. **miniwdl production compatibility**
   - The validator wrapper contract tests.
   - Representative structured compilation and explicit `miniwdl check`.
3. **Web lint, tests and build**
   - Locked npm installation, ESLint, Catalog retrieval tests, Workflow IR DAG
     tests, and the production Next.js build.

The aggregate job uses `if: always()` and fails unless every dependency
concludes with `success`. The `Mainline Safeguard` ruleset requires only the
stable `CI gate` context, so internal job names and future matrices can evolve
without weakening branch protection.

## Canonical WDL validator

WOMtool 92 is the canonical WDL syntax and type validation gate because the
project's execution runner targets Cromwell 92. CI sets
`WDL_VALIDATOR=womtool` and points `WOMTOOL_JAR` to the versioned JAR; it does
not use `auto`, so a missing WOMtool installation cannot silently fall back to
another validator.

The release asset is pinned by version, byte size, and SHA-256:

```text
Version: 92
Size: 123647806 bytes
SHA-256: 99cd3675c48696470f4d4e8b397fc613d7b342eb2ef2fa96f86db114bd9ed5f8
```

The checksum matches the digest published for the official Broad Institute
Cromwell 92 release asset. Java 17 is required and the workflow verifies both
the Java runtime and `womtool 92` before any test can run.

miniwdl remains a required secondary compatibility check while the production
API image uses `WDL_VALIDATOR=miniwdl`. It is not the canonical compiler
acceptance authority. If production moves to WOMtool later, miniwdl can become
an advisory portability check after an explicit compatibility decision.

## Local equivalents

Install Java and the checksum-verified WOMtool release from the repository
root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_java.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_womtool.ps1
```

Run the primary local checks:

```powershell
$env:WDL_VALIDATOR = "womtool"
$env:WOMTOOL_JAR = (Resolve-Path ".cache\womtool\womtool-92.jar").Path
powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1
```

Run the production validator compatibility check when changing WDL generation,
validation, or deployment behavior from Linux, macOS, or WSL:

```bash
uv sync --locked --extra miniwdl
WDL_VALIDATOR=miniwdl uv run --locked --extra miniwdl \
  main.py --input examples/rnaseq_deg_recipe_plan.json \
  --output .cache/ci/rnaseq_deg.wdl
uv run --locked --extra miniwdl miniwdl check \
  .cache/ci/rnaseq_deg.wdl
```

miniwdl imports POSIX-only modules and is not a native Windows validation
path. Windows contributors can run this check through WSL or rely on the
required Ubuntu CI job; WOMtool remains fully supported on native Windows.

Run the Web checks from `web/`:

```powershell
npm ci
npm run lint
npm run test:catalog-retrieval
npm run test:graph
npm run build
```

Real Cromwell execution and full project-maintained container builds remain
explicit opt-in checks. They require external services, images, or runner
state and are not part of the deterministic pull-request gate.

## Workflow security

- Pull-request jobs receive read-only repository permissions and no deployment
  secrets.
- The workflow does not use `pull_request_target`.
- Third-party actions are pinned to full commit SHAs.
- Checkout credentials are not persisted.
- Concurrent runs for an older commit on the same pull request are cancelled.
- Dependency lockfiles are enforced through `uv sync --locked` and `npm ci`.

The image publication and deployment workflows remain separate from this
required validation gate. They may use credentials only in their guarded
publish or deployment paths.
