# Workflow helper containers

Catalog entries may reference helper images when a workflow task depends on
project-maintained scripts. Build and publish images explicitly, then copy the
final tag or digest into the Tool Catalog YAML. The compiler never searches for
or fills in container images automatically.

Default tag pattern:

```bash
ghcr.io/yuanzhw/ai-bioworkflow/<tool>:<software-version>-<image-revision>
```

For example, DESeq2 `1.42.1` with the second project-maintained image
revision is published as:

```bash
ghcr.io/yuanzhw/ai-bioworkflow/deseq2:1.42.1-r2
```

The directory name and `TOOL_VERSION` build arg represent the upstream software
or package version. The image revision is stored in `image_revision.txt` under
the same container directory. Increment the revision whenever Dockerfile,
helper scripts, pinned dependencies, or runtime behavior changes while the
upstream tool version stays the same.

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

With `containers/deseq2/1.42.1/image_revision.txt` set to `r2`, this publishes
`ghcr.io/yuanzhw/ai-bioworkflow/deseq2:1.42.1-r2`.

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

The build script publishes revision tags, not bare software-version tags. A
bare tag such as `deseq2:1.42.1` may be maintained as a convenience alias
outside the formal Catalog, but Catalog entries should use revision tags first
and eventually promote to validated digests.

Each container directory should include:

- `Dockerfile`
- helper scripts copied into the image
- `smoke_test.sh` for a fast post-build check
- `image_revision.txt` containing a revision like `r1` or `r2`

Version rules:

- Directory names and `TOOL_VERSION` build args should match the upstream
  software version.
- Image tags should append the project-maintained image revision, for example
  `1.42.1-r2`.
- Dockerfiles must install the declared top-level tool version explicitly.
- Dockerfiles should fail during build if the installed top-level tool version
  does not match `TOOL_VERSION`.
- `smoke_test.sh` should verify the helper entrypoint and installed top-level
  tool version as a second check.
- Final reusable catalog entries should prefer a validated image digest over a
  mutable tag once the image has been published and inspected.
