ARG NODE_IMAGE=cgr.dev/chainguard/node:latest-dev@sha256:7f240e0b8a76496e6128948e4cfb0c3c145f629ac2b9d3cee3d554b746e82ca3
ARG NGINX_IMAGE=cgr.dev/chainguard/nginx:latest@sha256:65ad444a372b9f69821ef15acb95c46e9cffdd520bbdc4f8a72d5d38d7c1ca92

FROM ${NODE_IMAGE} AS builder

ARG PNPM_VERSION=11.7.0
ARG VITE_API_BASE_URL=
ARG VITE_OIDC_AUTHORITY=http://localhost:8080/realms/cybercontrol
ARG VITE_OIDC_CLIENT_ID=cybercontrol-workbench
ARG VITE_OIDC_SCOPE="openid profile email"

ENV COREPACK_HOME=/tmp/corepack \
    VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_OIDC_AUTHORITY=${VITE_OIDC_AUTHORITY} \
    VITE_OIDC_CLIENT_ID=${VITE_OIDC_CLIENT_ID} \
    VITE_OIDC_SCOPE=${VITE_OIDC_SCOPE}

WORKDIR /workspace

COPY --chown=65532:65532 frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml /workspace/frontend/
COPY --chown=65532:65532 packages/contracts-ts /workspace/packages/contracts-ts
RUN corepack "pnpm@${PNPM_VERSION}" --dir frontend install --frozen-lockfile

COPY --chown=65532:65532 frontend/index.html frontend/tsconfig.json frontend/tsconfig.app.json frontend/tsconfig.node.json /workspace/frontend/
COPY --chown=65532:65532 frontend/vite.config.ts /workspace/frontend/vite.config.ts
COPY --chown=65532:65532 frontend/public /workspace/frontend/public
COPY --chown=65532:65532 frontend/src /workspace/frontend/src
RUN corepack "pnpm@${PNPM_VERSION}" --dir frontend run build

FROM ${NGINX_IMAGE} AS runtime

COPY --chown=65532:65532 infra/nginx/frontend.conf /etc/nginx/conf.d/nginx.default.conf
COPY --from=builder --chown=65532:65532 /workspace/frontend/dist /usr/share/nginx/html

USER 65532:65532
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["/usr/sbin/nginx", "-t", "-c", "/etc/nginx/nginx.conf"]
