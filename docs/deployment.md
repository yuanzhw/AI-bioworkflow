# 部署与运维手册

本文档记录 AI-bioworkflow 作品集 demo 的本地与公开部署边界，以及当前生产部署方案。目标是让部署流程可以重复执行、可以审计、可以回滚，而不是依赖一次性的手工命令。

当前生产形态是单台阿里云 ECS 上运行 Docker Compose：

```text
GitHub main push
  -> GitHub Actions build API/Web images
  -> push images to Alibaba Cloud ACR
  -> SSH/SCP sync deployment files to ECS
  -> deploy-ecs.sh updates .env.images
  -> Docker Compose pulls images and starts services
  -> Caddy terminates HTTPS and reverse proxies traffic
```

## 运行模式与最短路径

当前仓库覆盖三种运行方式，公开作品集使用第二种：

| 模式 | 入口 | 数据位置 | 适用范围 |
| --- | --- | --- | --- |
| 本地联合开发 | `scripts/dev_local.ps1` 启动 FastAPI 与 Next.js | `.cache/ai-bioworkflow.sqlite3` | 开发、演示和跨页面回放 |
| 单机公开 demo | Caddy + API + Web 的 Docker Compose | `api_data` Docker volume | 当前 ECS 作品集部署 |
| 前后端分离 | 独立 Web 域名通过 HTTPS 调用 API 域名 | 由 API 部署决定 | 可选拓扑，需要显式配置 API base URL 与 CORS |

本地启动前可以先执行 dry run，检查 Python、Web 依赖和端口可用性，但不启动服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev_local.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File scripts\dev_local.ps1
```

默认地址是 FastAPI `127.0.0.1:8010` 和 Next.js `127.0.0.1:3000`。需要更换端口时，
联合启动脚本会同步生成 API base URL 和 CORS origins：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev_local.ps1 `
  -ApiPort 8020 `
  -WebPort 3001
```

结构化 RNA-seq 示例调用 `POST /api/compile`，不需要 `DEEPSEEK_API_KEY`。只有自然语言
入口 `POST /api/runs` 需要 Planner key。

## 环境变量边界

| 变量 | 生效阶段 | 默认值或当前生产值 | 用途与约束 |
| --- | --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | Web 镜像构建时 | 本地 `http://127.0.0.1:8010` | 浏览器可访问的 API 根地址。值会进入客户端 bundle，不能包含 secret；修改后必须重新构建 Web 镜像。 |
| `AI_BIOWORKFLOW_API_HOST` | `src.api.server` 本地启动时 | `127.0.0.1` | 控制开发服务器监听地址。生产 API 镜像直接以 `0.0.0.0:8010` 启动，不读取该变量。 |
| `AI_BIOWORKFLOW_API_PORT` | `src.api.server` 本地启动时 | `8010` | 控制开发服务器端口，允许 `1-65535`。生产容器端口固定为 `8010`。 |
| `AI_BIOWORKFLOW_CORS_ORIGINS` | API 运行时 | 本地允许 `127.0.0.1:3000` 和 `localhost:3000` | 逗号分隔的浏览器 origin。仅在 Web 与 API 跨 origin 时需要显式设置。 |
| `AI_BIOWORKFLOW_DB_PATH` | API 运行时 | 本地 `.cache/ai-bioworkflow.sqlite3`；容器 `/data/ai-bioworkflow/ai-bioworkflow.sqlite3` | SQLite 文件路径。生产路径位于 Compose `api_data` volume。 |
| `DEEPSEEK_API_KEY` | Planner 运行时 | 未设置 | 仅自然语言规划需要；结构化编译必须在无 key 时正常工作。只放在服务端 `.env.prod` 或 secret store。 |
| `WDL_VALIDATOR` | 编译运行时 | 本地 `auto`；生产 `miniwdl` | 可选值为 `auto`、`womtool`、`miniwdl`。生产镜像已安装 miniwdl。 |
| `AI_BIOWORKFLOW_RUN_BACKEND` | API 运行时 | `disabled` | 控制真实 WDL execution backend。作品集 demo 保持禁用，不把编译 timeline 表述为真实 call 执行状态。 |

`NEXT_PUBLIC_API_BASE_URL` 是构建时公开配置，`.env.prod` 是 API 容器运行时私有配置。
两者不能互相替代，也不要把 API key、token 或私有网络地址写入任何 `NEXT_PUBLIC_*`
变量。

## 同源、CORS 与反向代理

当前 ECS 方案使用单一 HTTPS 域名。浏览器请求同一域名的 `/api/*`，Caddy 再转发到
Docker 网络内的 `api:8010`，因此不产生跨 origin 请求，也不需要为生产域名额外放宽
CORS。

只有 Web 与 API 使用不同的 scheme、hostname 或 port 时，才需要同时配置：

1. 构建 Web 镜像时，将 `NEXT_PUBLIC_API_BASE_URL` 设置为公开 API 的 HTTPS 根地址。
2. 在 API `.env.prod` 中，将 `AI_BIOWORKFLOW_CORS_ORIGINS` 设置为实际 Web origins。

```text
NEXT_PUBLIC_API_BASE_URL=https://api.example.com
AI_BIOWORKFLOW_CORS_ORIGINS=https://portfolio.example.com,https://preview.example.com
```

origin 只写 scheme、hostname 和可选 port，不包含 path。CORS 只控制浏览器跨域访问，
不是认证或限流机制，不应使用它保护匿名公开 API。

## SQLite 与公开 demo 数据边界

SQLite 当前保存 run、event、artifact 和 diagnostic，连接启用 WAL、busy timeout 和
foreign keys，适合单机、单 API 服务的作品集流量。生产 Compose 的 `api_data` volume
可以跨容器重建保留数据，但它不是备份，也不能替代主机或云盘级恢复策略。

公开 demo 应遵守以下边界：

- 保持单个 API replica，不让多个主机共享同一个 SQLite 文件。
- 只使用可公开的示例请求，不保存真实受试者信息、凭证或私有数据路径。
- 明确保留策略：选择周期性重置匿名 run history，或定期备份 `api_data` volume。
- 执行数据重置前先停止 API 并备份数据库，避免在写入期间复制或替换 SQLite 文件。
- 需要多副本、较高并发或长期可靠保存时，再实现并验证 PostgreSQL repository；当前仓库尚未提供可直接切换的 PostgreSQL adapter。

当前 demo 没有登录、多租户、配额或 API rate limit。若在公开 API 中配置
`DEEPSEEK_API_KEY`，匿名访问者也可能触发模型调用并产生费用；广泛公开前应在反向代理
或应用层增加访问策略。仅展示确定性编译路径时，可以不配置该 key。

## 服务边界

当前 Compose 只启动三个服务：

| 服务 | 作用 | 对公网暴露 |
| --- | --- | --- |
| `proxy` | Caddy HTTPS 入口与反向代理 | Compose 默认绑定 `80/tcp`、`443/tcp`、`443/udp`；公网可达性取决于安全组和防火墙 |
| `api` | FastAPI 后端 | 不直接暴露，仅 Docker 网络内 `8010` |
| `web` | Next.js standalone 前端 | 不直接暴露，仅 Docker 网络内 `3000` |

生产入口统一使用 HTTPS 域名：

```text
https://your-domain.example.com/          -> web:3000
https://your-domain.example.com/api/...   -> api:8010
https://your-domain.example.com/docs      -> api:8010/docs
https://your-domain.example.com/redoc     -> api:8010/redoc
https://your-domain.example.com/health    -> api:8010/health
https://your-domain.example.com/version   -> api:8010/version
https://your-domain.example.com/api/version -> api:8010/api/version
```

这个部署不启动 Cromwell runner，也不默认执行真实 WDL 后端。API 运行时默认保持 `AI_BIOWORKFLOW_RUN_BACKEND=disabled`。

## ACR 配置

应用镜像发布到阿里云 ACR。建议为该项目准备一个独立 namespace，并保留两个仓库：

```text
ai-bioworkflow-api
ai-bioworkflow-web
```

GitHub Actions 需要以下 repository secrets：

| Secret | 示例 | 说明 |
| --- | --- | --- |
| `ACR_REGISTRY` | `registry.cn-hangzhou.aliyuncs.com` | ACR registry host，不带 `https://` 和路径 |
| `ACR_NAMESPACE` | `your-namespace` | ACR namespace，使用小写 Docker path component |
| `ACR_USERNAME` | `your-acr-username` | 有 push/pull 权限的 ACR 账号 |
| `ACR_PASSWORD` | `your-acr-password` | ACR 登录密码或访问凭证 |

`main` 分支 push 后，workflow 会构建并推送两个 tag：

```text
registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-api:<short-sha>
registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-api:latest
registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-web:<short-sha>
registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-web:latest
```

ECS 部署使用 commit SHA tag，而不是只依赖 `latest`。这样线上版本可追踪，回滚也能精确定位到上一版镜像。

## GitHub 配置

### Repository Variables

| Variable | 示例 | 说明 |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `https://your-domain.example.com` | 编译进 Web 镜像的浏览器可访问 API 根地址 |
| `ECS_DEPLOY_PATH` | `/opt/ai-bioworkflow` | 可选。ECS 上部署目录，未配置时使用默认值 |

`NEXT_PUBLIC_API_BASE_URL` 应使用最终给浏览器访问的 HTTPS 站点根地址。当前 Caddy 将 API 和 Web 放在同一个域名下，因此这里通常就是站点根地址，不要写 Docker 内部 hostname，也不要写 `localhost`。

域名是否带 `www` 取决于你想公开的主入口。选择一个 canonical 域名后，`AI_BIOWORKFLOW_SITE_ADDRESS`、`NEXT_PUBLIC_API_BASE_URL` 和 DNS 记录应保持一致。除非已经配置 `www` 的 DNS 和证书覆盖，否则不要临时在变量里混用两个域名。

### Repository Secrets

部署到 ECS 还需要以下 secrets：

| Secret | 说明 |
| --- | --- |
| `ECS_HOST` | ECS 公网 IP 或可解析 hostname |
| `ECS_USER` | SSH 登录用户 |
| `ECS_SSH_PRIVATE_KEY` | 用于登录 ECS 的私钥 |

可选 secrets：

| Secret | 默认值 | 说明 |
| --- | --- | --- |
| `ECS_SSH_PORT` | `22` | SSH 端口 |
| `ECS_KNOWN_HOSTS` | 动态 `ssh-keyscan` | 推荐配置。固定 ECS SSH host key，减少中间人风险 |

建议在可信网络环境中生成并核对 `ECS_KNOWN_HOSTS`：

```bash
ssh-keyscan -p <ecs-ssh-port> -H <ecs-public-ip-or-hostname>
```

`<ecs-ssh-port>` 使用实际的 `ECS_SSH_PORT`，未自定义时为 `22`。

未配置 `ECS_KNOWN_HOSTS` 时，workflow 会用带超时的 `ssh-keyscan` 动态生成 `known_hosts`。这能让自动部署跑起来，但安全性弱于固定 host key。

## ECS 目录与文件

建议部署目录：

```text
/opt/ai-bioworkflow
```

目录中的文件分为两类。

仓库管理并由 CI 同步：

| 文件 | 说明 |
| --- | --- |
| `docker-compose.prod.yml` | 生产 Compose 定义 |
| `Caddyfile` | HTTPS 入口和反向代理规则 |
| `scripts/deploy-ecs.sh` | ECS 部署脚本 |
| `scripts/preflight-ecs.sh` | ECS 部署前置检查脚本 |

只在 ECS 上维护，不提交到 Git：

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `.env.deploy` | `deploy/app/env.deploy.example` | ECS 固定配置，如域名、端口、Caddy 镜像 |
| `.env.prod` | `deploy/app/env.prod.example` | API 运行时配置和密钥 |
| `.env.images` | CI 自动生成，或从 `deploy/app/env.images.example` 复制 | 当前运行的 API/Web 镜像 |
| `.env.images.rollback` | 部署脚本自动备份 | 上一版镜像配置，用于失败自动回滚或手动恢复 |

这些真实环境文件已在 `.gitignore` 中忽略。不要提交 `.env.prod`、`.env.deploy`、`.env.images`、私钥、token 或 API key。

### `.env.deploy`

`.env.deploy` 保存 ECS 固定部署配置。示例：

```text
AI_BIOWORKFLOW_RUNTIME_ENV_FILE=./.env.prod

AI_BIOWORKFLOW_CADDY_IMAGE=caddy:2-alpine
AI_BIOWORKFLOW_SITE_ADDRESS=your-domain.example.com
AI_BIOWORKFLOW_TLS_EMAIL=you@example.com

AI_BIOWORKFLOW_HTTP_BIND=0.0.0.0
AI_BIOWORKFLOW_HTTP_PORT=80
AI_BIOWORKFLOW_HTTPS_BIND=0.0.0.0
AI_BIOWORKFLOW_HTTPS_PORT=443
```

`AI_BIOWORKFLOW_TLS_EMAIL` 用于 ACME 证书通知，可以是任意可接收邮件的邮箱，不要求必须是该域名下的邮箱。

如果 ECS 拉取 Docker Hub 的 `caddy:2-alpine` 不稳定，可以先把 Caddy 镜像同步到 ACR，再设置：

```text
AI_BIOWORKFLOW_CADDY_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/caddy:2-alpine
```

### `.env.prod`

`.env.prod` 是 API 容器读取的运行时配置。示例：

```text
AI_BIOWORKFLOW_RUN_BACKEND=disabled
WDL_VALIDATOR=miniwdl

# Required only when Web and API are served from different browser origins.
# AI_BIOWORKFLOW_CORS_ORIGINS=https://portfolio.example.com

# Required only when natural-language planning is enabled.
# DEEPSEEK_API_KEY=<your-deepseek-api-key>
```

真实 `.env.prod` 只保存在 ECS。自然语言规划需要 `DEEPSEEK_API_KEY`；结构化编译入口不应依赖该 key。

### `.env.images`

`.env.images` 保存当前要运行的不可变镜像引用：

```text
AI_BIOWORKFLOW_API_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-api:<short-sha>
AI_BIOWORKFLOW_WEB_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-web:<short-sha>
```

自动部署会重新生成该文件。不要把主机配置或密钥放进 `.env.images`，否则自动部署更新镜像时会覆盖掉这些内容。

## ECS 安全组建议

最小公开入站规则：

| 协议 | 端口 | 来源 | 用途 |
| --- | --- | --- | --- |
| TCP | `80` | `0.0.0.0/0`、`::/0` | HTTP 到 HTTPS 跳转、ACME 校验 |
| TCP | `443` | `0.0.0.0/0`、`::/0` | HTTPS 访问 |
| UDP | `443` | `0.0.0.0/0`、`::/0` | 可选，仅影响 Caddy HTTP/3；不影响普通 HTTPS over TCP |
| TCP | `22` 或自定义 SSH 端口 | 管理员固定 IP | SSH 部署与维护 |

不建议对公网开放：

```text
3000  # web container
8010  # api container
```

ECS 还需要允许出站 HTTPS，用于拉取 ACR 镜像、访问 Docker registry、完成 ACME 证书申请和访问外部 API。

## Caddy HTTPS

`deploy/app/Caddyfile` 使用 `AI_BIOWORKFLOW_SITE_ADDRESS` 和 `AI_BIOWORKFLOW_TLS_EMAIL`：

```caddyfile
{
	email {$AI_BIOWORKFLOW_TLS_EMAIL}
}

{$AI_BIOWORKFLOW_SITE_ADDRESS} {
	encode zstd gzip

	@api path /api /api/* /docs /docs/* /redoc /redoc/* /openapi.json /health /version
	reverse_proxy @api api:8010

	reverse_proxy web:3000
}
```

上线前检查：

1. 域名 A 记录已经指向 ECS 公网 IP。
2. ECS 安全组允许 `80/tcp` 和 `443/tcp`。
3. ECS 系统防火墙没有拦截 `80/443`。
4. `AI_BIOWORKFLOW_SITE_ADDRESS` 与实际访问域名一致。
5. Caddy 的 `caddy_data` volume 没有被误删；证书会保存在这里并自动续期。

如果证书申请失败，优先查看：

```bash
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml logs -f proxy
```

## 首次手动部署

在 ECS 上创建目录并复制示例文件：

```bash
sudo mkdir -p /opt/ai-bioworkflow
sudo chown -R "$USER":"$USER" /opt/ai-bioworkflow

cp deploy/app/docker-compose.prod.yml /opt/ai-bioworkflow/
cp deploy/app/Caddyfile /opt/ai-bioworkflow/
mkdir -p /opt/ai-bioworkflow/scripts
cp deploy/app/scripts/*.sh /opt/ai-bioworkflow/scripts/
cp deploy/app/env.deploy.example /opt/ai-bioworkflow/.env.deploy
cp deploy/app/env.images.example /opt/ai-bioworkflow/.env.images
cp deploy/app/env.prod.example /opt/ai-bioworkflow/.env.prod
chmod +x /opt/ai-bioworkflow/scripts/*.sh
```

编辑：

```text
/opt/ai-bioworkflow/.env.deploy
/opt/ai-bioworkflow/.env.prod
/opt/ai-bioworkflow/.env.images
```

然后执行：

```bash
cd /opt/ai-bioworkflow
./scripts/deploy-ecs.sh
```

部署后检查：

```bash
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml ps
curl -fsS https://your-domain.example.com/health
curl -fsS https://your-domain.example.com/api/recipes
curl -fsS https://your-domain.example.com/api/version
```

浏览器访问：

```text
https://your-domain.example.com/workspace?example=rnaseq-deg
```

## 手动发布指定镜像

如果要手动发布一个已经存在于 ACR 的 commit SHA tag：

```bash
cd /opt/ai-bioworkflow
AI_BIOWORKFLOW_API_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-api:<short-sha> \
AI_BIOWORKFLOW_WEB_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-web:<short-sha> \
./scripts/deploy-ecs.sh
```

脚本会：

1. 运行 `scripts/preflight-ecs.sh`，检查 Docker、Compose、部署目录、环境文件、端口配置、磁盘空间和 Compose 配置。
2. 校验部署目录、Compose 文件、`.env.deploy`、`.env.prod` 和镜像引用。
3. 在写入新 `.env.images` 前备份当前文件为 `.env.images.rollback`。
4. 执行 `docker compose config`、`pull`、`up -d --remove-orphans` 和 `ps`。
5. 默认检查 `/health` 和 `/api/recipes`。
6. 如果新版本启动或健康检查失败，恢复 `.env.images.rollback` 并重新拉起上一版。

健康检查参数：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AI_BIOWORKFLOW_HEALTH_ATTEMPTS` | `12` | 重试次数 |
| `AI_BIOWORKFLOW_HEALTH_DELAY_SECONDS` | `5` | 重试间隔 |
| `AI_BIOWORKFLOW_HEALTH_CONNECT_TIMEOUT_SECONDS` | `5` | curl 连接超时 |
| `AI_BIOWORKFLOW_HEALTH_MAX_TIME_SECONDS` | `15` | curl 总超时 |
| `AI_BIOWORKFLOW_SKIP_HEALTHCHECK` | `false` | 是否跳过健康检查 |

这些参数会在写入新 `.env.images` 之前校验。配置不合法时，部署会直接失败，不会覆盖当前镜像配置。

preflight 默认启用。可选参数：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AI_BIOWORKFLOW_SKIP_PREFLIGHT` | `false` | 临时跳过 preflight |
| `AI_BIOWORKFLOW_PREFLIGHT_MIN_FREE_MB` | `512` | 部署目录所在文件系统的最小可用空间 |

单独运行 preflight：

```bash
cd /opt/ai-bioworkflow
./scripts/preflight-ecs.sh
```

## 自动部署

`.github/workflows/build-app-images.yml` 在 `main` 分支 push 后自动执行：

1. 构建 API 镜像。
2. 构建 Web 镜像，并注入 `NEXT_PUBLIC_API_BASE_URL`。
3. 推送 API/Web 镜像到 ACR。
4. 通过 SSH 连接 ECS。
5. 同步仓库管理的部署文件。
6. 用当前 commit SHA tag 生成 `.env.images`。
7. 执行 `./scripts/deploy-ecs.sh`。

workflow 只在会影响应用镜像或生产部署行为的路径变化时触发，例如
`.github/workflows/build-app-images.yml`、`src/**`、`web/**`、
`deploy/app/api/**`、`deploy/app/web/**`、`deploy/app/Caddyfile`、
`deploy/app/docker-compose.prod.yml` 和 `deploy/app/scripts/**`。单纯修改
`docs/**`、`deploy/app/README.md` 或 env example 不会触发生产部署。

构建时会将 commit SHA、镜像 tag 和 UTC build time 写入 API/Web 镜像。线上可通过
以下地址查看当前部署版本：

```bash
curl -fsS https://your-domain.example.com/api/version
curl -fsS https://your-domain.example.com/version
```

部署 job 使用 concurrency：

```text
ecs-app-deploy-${{ github.repository }}
```

因此同一个仓库不会并发执行多个 ECS 部署。后来的部署会排队等待，避免同时改写 `.env.images` 或并发操作 Compose。

自动部署不会覆盖 ECS 上的 `.env.deploy` 和 `.env.prod`。这两个文件是主机级配置，需要在 ECS 上维护。

## 回滚

### 自动回滚

默认启用失败自动回滚。只要部署时传入了新的 API/Web 镜像，脚本会先备份当前 `.env.images`：

```text
.env.images.rollback
```

如果新版本在 Compose 操作或健康检查阶段失败，脚本会恢复上一版 `.env.images` 并重新执行 Compose。GitHub Actions job 仍会失败，这是期望行为：它表示新版本没有成功上线，但线上服务已经尽力恢复到上一版。

临时关闭自动回滚：

```bash
AI_BIOWORKFLOW_ROLLBACK_ON_FAILURE=false ./scripts/deploy-ecs.sh
```

### 手动回滚

方式一：恢复自动备份：

```bash
cd /opt/ai-bioworkflow
cp .env.images.rollback .env.images
./scripts/deploy-ecs.sh
```

方式二：手动指定一个已知可用的 commit SHA tag：

```bash
cd /opt/ai-bioworkflow
AI_BIOWORKFLOW_API_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-api:<known-good-sha> \
AI_BIOWORKFLOW_WEB_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-web:<known-good-sha> \
./scripts/deploy-ecs.sh
```

回滚后确认：

```bash
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml ps
curl -fsS https://your-domain.example.com/health
curl -fsS https://your-domain.example.com/api/recipes
```

## 常用排查命令

查看服务状态：

```bash
cd /opt/ai-bioworkflow
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml ps
```

查看日志：

```bash
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml logs -f proxy
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml logs -f api
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml logs -f web
```

查看线上版本：

```bash
curl -fsS https://your-domain.example.com/api/version
cat .env.images
```

验证 Compose 配置：

```bash
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml config
```

手动拉取镜像：

```bash
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml pull
```

## 常见问题

### `AI_BIOWORKFLOW_SITE_ADDRESS is missing`

Compose 在插值阶段读取不到 `.env.deploy`，或 `.env.deploy` 里没有设置该变量。确认命令包含：

```bash
--env-file .env.deploy --env-file .env.images
```

并检查 `.env.deploy` 中存在：

```text
AI_BIOWORKFLOW_SITE_ADDRESS=your-domain.example.com
```

### `invalid reference format`

通常是镜像引用为空或格式不完整，例如仓库地址部分缺失导致 `:tag`。检查：

```bash
cat .env.images
```

应包含完整镜像：

```text
AI_BIOWORKFLOW_API_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-api:<short-sha>
AI_BIOWORKFLOW_WEB_IMAGE=registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-web:<short-sha>
```

当前 workflow 会在 deploy job 内重新拼接镜像引用，并对 registry、namespace、image name 和 tag 做格式校验，避免由 secret 派生的空输出跨 job 传播。

### HTTPS 访问不了

按顺序检查：

1. 域名 A 记录是否指向 ECS 公网 IP。
2. ECS 安全组是否开放 `80/tcp` 和 `443/tcp`。
3. 服务器防火墙是否允许 `80/443`。
4. Caddy 是否正常启动。
5. `AI_BIOWORKFLOW_SITE_ADDRESS` 是否和访问域名一致。

命令：

```bash
docker compose --env-file .env.deploy --env-file .env.images -f docker-compose.prod.yml logs -f proxy
curl -I http://your-domain.example.com
curl -I https://your-domain.example.com
```

### 页面能打开但 API 请求失败

检查 Web 镜像构建时的 `NEXT_PUBLIC_API_BASE_URL`。生产环境应为 HTTPS 站点根地址：

```text
NEXT_PUBLIC_API_BASE_URL=https://your-domain.example.com
```

如果该值曾经设置为 `http://localhost:8010` 或旧域名，需要重新构建并发布 Web 镜像。

### ACR 拉取失败

检查：

1. ECS 能否访问 ACR registry。
2. ECS 上 Docker 是否已经登录 ACR，或 ACR 仓库是否允许当前拉取方式。
3. `.env.images` 中 registry、namespace、repository 和 tag 是否存在。
4. GitHub Actions 是否已经成功 push 该 commit SHA tag。

手动验证：

```bash
docker pull registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-api:<short-sha>
docker pull registry.cn-hangzhou.aliyuncs.com/your-namespace/ai-bioworkflow-web:<short-sha>
```

### Preflight 失败

按错误信息检查 Docker daemon、Docker Compose plugin、部署目录权限、`.env.deploy`、
`.env.prod`、镜像引用和磁盘空间。默认要求部署目录所在文件系统至少有 `512MB`
可用空间；可以通过 `AI_BIOWORKFLOW_PREFLIGHT_MIN_FREE_MB` 调整。

## 运维检查清单

首次上线前：

- ACR namespace 和 API/Web repository 已创建。
- GitHub ACR secrets 已配置。
- GitHub ECS secrets 已配置。
- `NEXT_PUBLIC_API_BASE_URL` 已配置为 HTTPS 站点根地址。
- DNS A 记录指向 ECS 公网 IP。
- ECS 安全组开放 `80/tcp`、`443/tcp`，SSH 只对可信 IP 开放。
- ECS `/opt/ai-bioworkflow/.env.deploy` 已配置。
- ECS `/opt/ai-bioworkflow/.env.prod` 已配置，且未提交到 Git。
- Docker 和 Docker Compose plugin 在 ECS 上可用。
- ECS 可以拉取 ACR 镜像。

每次发布后：

- GitHub Actions build 和 deploy job 成功。
- ECS `docker compose ps` 显示 `proxy`、`api`、`web` 正常运行。
- `https://your-domain.example.com/health` 返回成功。
- `https://your-domain.example.com/api/recipes` 返回成功。
- `https://your-domain.example.com/api/version` 显示预期 commit SHA 或 tag。
- `https://your-domain.example.com/workspace?example=rnaseq-deg` 可以触发示例编译。

## 可选后续运维打磨

这些不是当前自动部署链路的必要条件，可以在后续项目打磨阶段逐步补齐：

- 外部站点监控和告警：定期检查 `/`、`/health`、`/api/recipes` 和 `/api/version`，连续失败后通过邮件、短信或 IM 通知。
- 多版本发布历史：保留多份 `.env.images` release 记录，支持回滚到指定 commit SHA。
- 镜像 digest 固定：部署时记录或使用 ACR 返回的 image digest，进一步避免 tag 被覆盖带来的不确定性。
- GitHub Environment 保护：对 production 部署增加手动审批、部署窗口或分支保护策略。
- 数据备份：定期备份 API SQLite volume，记录恢复步骤。
- 主机指标监控：通过阿里云 CloudMonitor 或其它监控系统覆盖 CPU、内存、磁盘、Docker daemon 和容器状态。
