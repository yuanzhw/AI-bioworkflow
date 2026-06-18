# syntax=docker/dockerfile:1

FROM node:22-slim AS deps

WORKDIR /app

COPY web/package.json web/package-lock.json ./
RUN npm ci

FROM node:22-slim AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

ARG NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8010
ARG NEXT_PUBLIC_BUILD_SHA=unknown
ARG NEXT_PUBLIC_BUILD_TAG=local
ARG NEXT_PUBLIC_BUILD_TIME=unknown
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_BUILD_SHA=${NEXT_PUBLIC_BUILD_SHA} \
    NEXT_PUBLIC_BUILD_TAG=${NEXT_PUBLIC_BUILD_TAG} \
    NEXT_PUBLIC_BUILD_TIME=${NEXT_PUBLIC_BUILD_TIME}

COPY --from=deps /app/node_modules ./node_modules
COPY web ./
RUN npm run build

FROM node:22-slim AS runner

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 nextjs

ARG NEXT_PUBLIC_BUILD_SHA=unknown
ARG NEXT_PUBLIC_BUILD_TAG=local
ARG NEXT_PUBLIC_BUILD_TIME=unknown

ENV NEXT_PUBLIC_BUILD_SHA=${NEXT_PUBLIC_BUILD_SHA} \
    NEXT_PUBLIC_BUILD_TAG=${NEXT_PUBLIC_BUILD_TAG} \
    NEXT_PUBLIC_BUILD_TIME=${NEXT_PUBLIC_BUILD_TIME}

COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "const http = require('http'); const port = process.env.PORT || 3000; const req = http.get({ host: '127.0.0.1', port, path: '/' }, (res) => process.exit(res.statusCode >= 200 && res.statusCode < 400 ? 0 : 1)); req.on('error', () => process.exit(1)); req.setTimeout(3000, () => { req.destroy(); process.exit(1); });"

CMD ["node", "server.js"]
