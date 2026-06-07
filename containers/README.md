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

Useful options:

```bash
python scripts/build_container.py multiqc 1.21 --dry-run
python scripts/build_container.py deseq2 1.42.0 --platform linux/amd64
python scripts/build_container.py tximport 1.30.0 --skip-smoke
```

The build script does not update Tool Catalog YAML files. After publishing,
copy the chosen tag or validated digest into the matching catalog entry
explicitly.

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
