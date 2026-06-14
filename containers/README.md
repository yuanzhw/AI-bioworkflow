# 工作流辅助容器

当 workflow task 依赖项目维护的辅助脚本时，Tool Catalog 条目可以引用对应的辅助镜像。镜像必须由维护者显式构建、验证和发布，然后把最终 tag 或 digest 写入 Tool Catalog YAML。编译器不会自动搜索、推断或补全容器镜像。

默认 tag 模式：

```bash
ghcr.io/yuanzhw/ai-bioworkflow/<tool>:<software-version>-<image-revision>
```

例如，DESeq2 `1.42.1` 的第二个项目维护镜像 revision 发布为：

```bash
ghcr.io/yuanzhw/ai-bioworkflow/deseq2:1.42.1-r2
```

目录名和 `TOOL_VERSION` 构建参数表示上游软件或包版本。镜像 revision 存放在同一容器目录下的 `image_revision.txt` 中。当 Dockerfile、辅助脚本、固定依赖或 runtime 行为发生变化，而上游工具版本保持不变时，需要递增该 revision。

构建单个镜像并运行 smoke test：

```bash
python scripts/build_container.py tximport 1.30.0
```

构建所有项目维护镜像：

```bash
python scripts/build_container.py --all
```

构建和 smoke test 成功后推送镜像：

```bash
docker login ghcr.io
python scripts/build_container.py --all --push
```

GitHub Actions 也可以构建这些镜像。Pull request 只运行 dry-run 校验 job，因此不会发布镜像。workflow 文件合并到默认分支后，可以从以下入口手动运行：

```text
Actions -> Build containers -> Run workflow
```

推荐首次运行：

```text
tool=all
publish=false
platform=linux/amd64
```

这会构建所有项目维护镜像并运行 smoke tests，但不会推送任何镜像。smoke tests 通过后，可以再次从 `main` 分支运行 workflow，并设置：

```text
tool=all
publish=true
platform=linux/amd64
```

构建单个镜像时，选择 tool 并提供版本，例如：

```text
tool=deseq2
version=1.42.1
publish=true
platform=linux/amd64
```

当 `containers/deseq2/1.42.1/image_revision.txt` 设置为 `r2` 时，上述配置会发布：

```text
ghcr.io/yuanzhw/ai-bioworkflow/deseq2:1.42.1-r2
```

该 workflow 使用 `GITHUB_TOKEN` 登录 GHCR，并且只有从 `main` 手动触发时才会发布镜像。首次发布后，需要在 GHCR 中确认 package 已关联到本仓库，并检查可见性是否符合预期。

常用选项：

```bash
python scripts/build_container.py multiqc 1.21 --dry-run
python scripts/build_container.py deseq2 1.42.1 --platform linux/amd64
python scripts/build_container.py tximport 1.30.0 --skip-smoke
```

构建脚本不会更新 Tool Catalog YAML 文件。镜像发布后，需要把选定的 tag 或已验证 digest 显式复制到对应 Catalog 条目中。

构建脚本发布 revision tags，而不是裸的软件版本 tags。类似 `deseq2:1.42.1` 的裸 tag 可以在正式 Catalog 之外作为便捷 alias 维护，但 Catalog 条目应优先使用 revision tag，并在后续迁移到已验证 digest。

每个容器目录应包含：

- `Dockerfile`
- 复制进镜像的辅助脚本
- 用于快速构建后检查的 `smoke_test.sh`
- 包含 `r1` 或 `r2` 这类 revision 的 `image_revision.txt`

版本规则：

- 目录名和 `TOOL_VERSION` 构建参数应匹配上游软件版本。
- 镜像 tag 应追加项目维护的镜像 revision，例如 `1.42.1-r2`。
- Dockerfile 必须显式安装声明的顶层工具版本。
- 如果安装后的顶层工具版本与 `TOOL_VERSION` 不一致，Dockerfile 应在 build 阶段失败。
- `smoke_test.sh` 应再次验证辅助入口命令和已安装的顶层工具版本。
- 最终可复用的 Catalog 条目应优先使用已验证 image digest，而不是可变 tag。
