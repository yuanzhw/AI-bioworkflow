# Workflow helper containers

Catalog entries may reference helper images when a workflow task depends on
project-maintained scripts. Build and publish images explicitly, then copy the
final tag or digest into the Tool Catalog YAML. The compiler never searches for
or fills in container images automatically.

Default tag pattern:

```bash
ghcr.io/yuanzhw/ai-bioworkflow/<tool>:<version>
```

Each container directory should include:

- `Dockerfile`
- helper scripts copied into the image
- `smoke_test.sh` for a fast post-build check
