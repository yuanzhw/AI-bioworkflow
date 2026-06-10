# Workflow helper containers

Catalog entries may reference helper images when a workflow task depends on
project-maintained scripts. Build and publish images explicitly, then copy the
final tag or digest into the Tool Catalog YAML. The compiler never searches for
or fills in container images automatically.

Default tag pattern:

```bash
ghcr.io/yuanzhw/ai-bioworkflow/<tool>:<version>
```

Build one image and run its smoke test:

```bash
python scripts/build_container.py tximport 1.30.0
```

Build every project-maintained image:

```bash
python scripts/build_container.py --all
```

Push after successful build and smoke test:

```bash
docker login ghcr.io
python scripts/build_container.py --all --push
```

GitHub Actions can also build these images. Pull requests run only a dry-run
validation job, so they never publish images. After the workflow file is merged
to the default branch, run it manually from:

```text
Actions -> Build containers -> Run workflow
```

Recommended first run:

```text
tool=all
publish=false
platform=linux/amd64
```

This builds all project-maintained images and runs their smoke tests without
pushing anything. To publish after the smoke tests pass, run the workflow again
from the `main` branch with:

```text
tool=all
publish=true
platform=linux/amd64
```

For a single image, choose the tool and provide its version, for example:

```text
tool=deseq2
version=1.42.1
publish=true
platform=linux/amd64
```

The workflow uses `GITHUB_TOKEN` to log in to GHCR and can only publish when
manually triggered from `main`. After the first publish, confirm in GHCR that
the package is associated with this repository and that its visibility is what
you expect.

Useful options:

```bash
python scripts/build_container.py multiqc 1.21 --dry-run
python scripts/build_container.py deseq2 1.42.1 --platform linux/amd64
python scripts/build_container.py tximport 1.30.0 --skip-smoke
```

The build script does not update Tool Catalog YAML files. After publishing,
copy the chosen tag or validated digest into the matching catalog entry
explicitly.

This workflow still publishes mutable version tags. Promoting catalog entries
to validated image digests is a separate follow-up step.

Each container directory should include:

- `Dockerfile`
- helper scripts copied into the image
- `smoke_test.sh` for a fast post-build check

Version rules:

- Directory names, image tags, and `TOOL_VERSION` build args should match.
- Dockerfiles must install the declared top-level tool version explicitly.
- Dockerfiles should fail during build if the installed top-level tool version
  does not match `TOOL_VERSION`.
- `smoke_test.sh` should verify the helper entrypoint and installed top-level
  tool version as a second check.
- Final reusable catalog entries should prefer a validated image digest over a
  mutable tag once the image has been published and inspected.
