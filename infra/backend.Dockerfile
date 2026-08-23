ARG PYTHON_IMAGE=python:3.11-alpine@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4

FROM ${PYTHON_IMAGE} AS builder

ARG UV_VERSION=0.11.28
ARG PYTHON_PACKAGE_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PYTHON_PACKAGE_INDEX_URL} \
    UV_DEFAULT_INDEX=${PYTHON_PACKAGE_INDEX_URL} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

WORKDIR /app
RUN python -m pip install "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock .python-version /app/
COPY backend /app/backend
COPY packages/contracts-python /app/packages/contracts-python

RUN uv sync --frozen --no-dev --all-packages --no-editable --extra retrieval

FROM ${PYTHON_IMAGE} AS runtime

ARG CYBERCONTROL_SOURCE_SHA=unknown
ARG CYBERCONTROL_SOURCE_TREE=unknown
ARG CYBERCONTROL_PRODUCT_SOURCE_SHA=unknown
ARG CYBERCONTROL_ENGINEERING_BASELINE_SHA=unknown
ARG CYBERCONTROL_PROCESS_VERSION=unknown

LABEL org.opencontainers.image.revision=${CYBERCONTROL_SOURCE_SHA} \
    com.cybercontrol.source-tree=${CYBERCONTROL_SOURCE_TREE} \
    com.cybercontrol.product-source=${CYBERCONTROL_PRODUCT_SOURCE_SHA} \
    com.cybercontrol.engineering-baseline=${CYBERCONTROL_ENGINEERING_BASELINE_SHA} \
    com.cybercontrol.process-version=${CYBERCONTROL_PROCESS_VERSION}

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LIYAN_REPOSITORY_ROOT=/app

RUN apk add --no-cache "jemalloc=5.3.0-r6" \
    && python -m pip uninstall --yes setuptools wheel \
    && python -m pip uninstall --yes pip \
    && addgroup -S -g 10001 liyans \
    && adduser -S -D -H -u 10001 -G liyans -h /app -s /sbin/nologin liyans \
    && mkdir -p /app/backend /app/config /app/var/artifacts \
        /var/lib/liyans/artifacts /var/lib/liyans/audit \
    && chown -R liyans:liyans /app /var/lib/liyans

ENV PYTHONMALLOC=malloc \
    LD_PRELOAD=/usr/lib/libjemalloc.so.2 \
    MALLOC_CONF=background_thread:true,dirty_decay_ms:1000,muzzy_decay_ms:1000,narenas:1,retain:false

COPY --from=builder --chown=liyans:liyans /app/.venv /app/.venv
COPY --chown=liyans:liyans backend/alembic.ini /app/backend/alembic.ini
COPY --chown=liyans:liyans backend/migrations /app/backend/migrations
COPY --chown=liyans:liyans config /app/config

WORKDIR /app/backend
USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]

CMD ["uvicorn", "liyans.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
