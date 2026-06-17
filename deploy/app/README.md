# 应用部署

本目录包含 AI-bioworkflow 作品集 demo 的应用镜像定义，以及面向单台
阿里云 ECS 的 Docker Compose 部署骨架。

这里的文件只启动 FastAPI 后端和 Next.js 前端，不启动 Cromwell，也不运行
workflow task 容器。Cromwell runner 仍独立维护在 `deploy/cromwell/`。

## 镜像

在仓库根目录构建 FastAPI API 镜像：

```bash
docker build \
  -f deploy/app/api/Dockerfile \
  -t ai-bioworkflow-api:local \
  .
```

在仓库根目录构建 Next.js Web 镜像：

```bash
docker build \
  -f deploy/app/web/Dockerfile \
  -t ai-bioworkflow-web:local \
  --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8010 \
  .
```

生产环境构建 Web 镜像时，`NEXT_PUBLIC_API_BASE_URL` 应设置为浏览器可访问的
HTTPS 站点根地址，例如 `https://your-domain.example.com`，而不是 Docker 内部
hostname 或 `localhost`。

## API 运行时

API 镜像暴露 `8010` 端口，启动命令为：

```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8010
```

容器内监听地址固定为 `0.0.0.0:8010`，不通过 `.env.prod` 配置；
公网入口由 Caddy proxy 统一暴露。

运行时环境变量：

```text
AI_BIOWORKFLOW_DB_PATH=/data/ai-bioworkflow/ai-bioworkflow.sqlite3
AI_BIOWORKFLOW_RUN_BACKEND=disabled
WDL_VALIDATOR=miniwdl
DEEPSEEK_API_KEY=<仅自然语言规划需要>
```

如果需要在容器替换后保留 run 历史记录，应持久化挂载
`/data/ai-bioworkflow`。

## Web 运行时

Web 镜像暴露 `3000` 端口，并运行 Next.js standalone server：

```bash
node server.js
```

前端 API base URL 通过构建参数 `NEXT_PUBLIC_API_BASE_URL` 写入镜像。

## 本地 Smoke Test

```bash
docker run --rm -p 8010:8010 ai-bioworkflow-api:local
docker run --rm -p 3000:3000 ai-bioworkflow-web:local
```

健康检查地址：

```text
API: http://localhost:8010/health
Web: http://localhost:3000/
```

## ECS Compose 骨架

将部署文件复制到 ECS 主机：

```bash
sudo mkdir -p /opt/ai-bioworkflow
sudo chown -R "$USER":"$USER" /opt/ai-bioworkflow

cp deploy/app/docker-compose.prod.yml /opt/ai-bioworkflow/
cp deploy/app/Caddyfile /opt/ai-bioworkflow/
mkdir -p /opt/ai-bioworkflow/scripts
cp deploy/app/scripts/deploy-ecs.sh /opt/ai-bioworkflow/scripts/
cp deploy/app/env.deploy.example /opt/ai-bioworkflow/.env.deploy
cp deploy/app/env.images.example /opt/ai-bioworkflow/.env.images
cp deploy/app/env.prod.example /opt/ai-bioworkflow/.env.prod
chmod +x /opt/ai-bioworkflow/scripts/deploy-ecs.sh
```

编辑 `/opt/ai-bioworkflow/.env.deploy`，设置域名和证书通知邮箱等 ECS 固定配置：

```text
AI_BIOWORKFLOW_RUNTIME_ENV_FILE=./.env.prod

AI_BIOWORKFLOW_SITE_ADDRESS=your-domain.example.com
AI_BIOWORKFLOW_TLS_EMAIL=you@example.com
```

编辑 `/opt/ai-bioworkflow/.env.images`，设置当前要运行的不可变镜像 tag：

```text
AI_BIOWORKFLOW_API_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-api:<commit-sha>
AI_BIOWORKFLOW_WEB_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-web:<commit-sha>
```

编辑 `/opt/ai-bioworkflow/.env.prod`，填写运行时配置。真实密钥只保存在 ECS：

```text
AI_BIOWORKFLOW_RUN_BACKEND=disabled
WDL_VALIDATOR=miniwdl
DEEPSEEK_API_KEY=<your-deepseek-api-key>
```

启动或更新应用：

```bash
cd /opt/ai-bioworkflow
./scripts/deploy-ecs.sh
```

也可以直接执行 Compose 命令：

```bash
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml pull
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml up -d --remove-orphans
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml ps
```

默认情况下，只有 Caddy proxy 服务发布到宿主机 `80/443`。API 和 Web 服务
不直接发布宿主机端口，只在 Docker 网络内暴露容器端口：API `8010`、Web
`3000`。公网入口统一为：

```text
https://your-domain.example.com/          -> web:3000
https://your-domain.example.com/api/...   -> api:8010
https://your-domain.example.com/docs      -> api:8010/docs
https://your-domain.example.com/health    -> api:8010/health
```

API run 历史记录保存在 Docker named volume `ai-bioworkflow_api_data`，
容器内挂载路径为 `/data/ai-bioworkflow`。

## HTTPS 入口

生产入口由 `deploy/app/Caddyfile` 定义。Caddy 会自动申请和续期证书，并将
HTTP 请求重定向到 HTTPS。

上线前确认：

- 域名 A 记录已经指向 ECS 公网 IP。
- ECS 安全组允许入站 TCP `80` 和 `443`。
- ECS 防火墙没有拦截 `80/443`。
- `3000` 和 `8010` 不需要对公网开放。

如果 ECS 无法直接拉取 Docker Hub 的 `caddy:2-alpine`，可以将 Caddy 镜像同步
到 ACR 后，在 `.env.deploy` 中设置：

```text
AI_BIOWORKFLOW_CADDY_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/caddy:2-alpine
```

启动后可用以下命令检查：

```bash
docker compose --env-file .env.deploy -f docker-compose.prod.yml logs -f proxy
curl -I http://your-domain.example.com
curl https://your-domain.example.com/health
curl https://your-domain.example.com/api/recipes
```

浏览器访问应用时应使用 HTTPS 域名，不再使用 `:3000`：

```text
https://your-domain.example.com/workspace?example=rnaseq-deg
```

## CI 构建并推送 ACR

应用镜像由 `.github/workflows/build-app-images.yml` 构建。默认行为：

- `main` 分支收到 push 时，构建 API 和 Web 镜像并推送到阿里云 ACR。
- 手动触发 `workflow_dispatch` 时，可以选择只构建不推送，或指定自定义 tag。
- 每次发布都会推送两个 tag：短 commit SHA 和 `latest`。

需要在 GitHub repository secrets 中配置：

```text
ACR_REGISTRY=registry.cn-hangzhou.aliyuncs.com
ACR_NAMESPACE=your-namespace
ACR_USERNAME=your-acr-username
ACR_PASSWORD=your-acr-password
```

建议在 GitHub repository variables 中配置 Web 构建时使用的公开 API 地址：

```text
NEXT_PUBLIC_API_BASE_URL=https://your-domain.example.com
```

CI 推送后的镜像形式为：

```text
registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-api:<commit-sha>
registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-api:latest
registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-web:<commit-sha>
registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-web:latest
```

ECS 部署时优先在 `.env.images` 中使用 commit SHA tag，而不是只依赖
`latest`。这样可以明确知道线上运行版本，也方便回滚。后续自动部署只应更新
`.env.images`，不要覆盖 `.env.deploy` 或 `.env.prod`。

## ECS 部署脚本

`deploy/app/scripts/deploy-ecs.sh` 用于在 ECS 上执行一次部署。它会：

- 校验 `docker-compose.prod.yml`、`.env.deploy`、`.env.prod` 和 `.env.images`。
- 在传入 `AI_BIOWORKFLOW_API_IMAGE` 和 `AI_BIOWORKFLOW_WEB_IMAGE` 时重新生成
  `.env.images`。
- 执行 `docker compose config`、`pull`、`up -d --remove-orphans` 和 `ps`。
- 默认检查 `https://<AI_BIOWORKFLOW_SITE_ADDRESS>/health` 和
  `https://<AI_BIOWORKFLOW_SITE_ADDRESS>/api/recipes`。

手动部署新镜像：

```bash
cd /opt/ai-bioworkflow
AI_BIOWORKFLOW_API_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-api:<commit-sha> \
AI_BIOWORKFLOW_WEB_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-web:<commit-sha> \
./scripts/deploy-ecs.sh
```

如果只想复用现有 `.env.images` 重启服务：

```bash
cd /opt/ai-bioworkflow
./scripts/deploy-ecs.sh
```

## 手动回滚

将 `/opt/ai-bioworkflow/.env.images` 中的镜像 tag 改回已知可用的 commit SHA，
然后执行：

```bash
cd /opt/ai-bioworkflow
./scripts/deploy-ecs.sh
```
