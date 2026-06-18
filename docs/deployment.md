# 生产部署与运维手册

本文档记录 AI-bioworkflow 作品集 demo 当前的生产部署方案。目标是让部署流程可以重复执行、可以审计、可以回滚，而不是依赖一次性的手工命令。

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

	@api path /api /api/* /docs /docs/* /redoc /redoc/* /openapi.json /health
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
cp deploy/app/scripts/deploy-ecs.sh /opt/ai-bioworkflow/scripts/
cp deploy/app/env.deploy.example /opt/ai-bioworkflow/.env.deploy
cp deploy/app/env.images.example /opt/ai-bioworkflow/.env.images
cp deploy/app/env.prod.example /opt/ai-bioworkflow/.env.prod
chmod +x /opt/ai-bioworkflow/scripts/deploy-ecs.sh
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

1. 校验部署目录、Compose 文件、`.env.deploy`、`.env.prod` 和镜像引用。
2. 在写入新 `.env.images` 前备份当前文件为 `.env.images.rollback`。
3. 执行 `docker compose config`、`pull`、`up -d --remove-orphans` 和 `ps`。
4. 默认检查 `/health` 和 `/api/recipes`。
5. 如果新版本启动或健康检查失败，恢复 `.env.images.rollback` 并重新拉起上一版。

健康检查参数：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AI_BIOWORKFLOW_HEALTH_ATTEMPTS` | `12` | 重试次数 |
| `AI_BIOWORKFLOW_HEALTH_DELAY_SECONDS` | `5` | 重试间隔 |
| `AI_BIOWORKFLOW_HEALTH_CONNECT_TIMEOUT_SECONDS` | `5` | curl 连接超时 |
| `AI_BIOWORKFLOW_HEALTH_MAX_TIME_SECONDS` | `15` | curl 总超时 |
| `AI_BIOWORKFLOW_SKIP_HEALTHCHECK` | `false` | 是否跳过健康检查 |

这些参数会在写入新 `.env.images` 之前校验。配置不合法时，部署会直接失败，不会覆盖当前镜像配置。

## 自动部署

`.github/workflows/build-app-images.yml` 在 `main` 分支 push 后自动执行：

1. 构建 API 镜像。
2. 构建 Web 镜像，并注入 `NEXT_PUBLIC_API_BASE_URL`。
3. 推送 API/Web 镜像到 ACR。
4. 通过 SSH 连接 ECS。
5. 同步仓库管理的部署文件。
6. 用当前 commit SHA tag 生成 `.env.images`。
7. 执行 `./scripts/deploy-ecs.sh`。

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
- `https://your-domain.example.com/workspace?example=rnaseq-deg` 可以触发示例编译。
