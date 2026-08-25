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

RUN uv sync --frozen --no-dev --all-packages --no-editable --extra retrieval \
    && find /app/.venv -path '*/site-packages/*.dist-info/uv_cache.json' \
        -type f -delete \
    && find /app/.venv -path '*/site-packages/*.dist-info/RECORD' \
        -type f -exec sed -i '/\/uv_cache\.json,/d' '{}' +

FROM ${PYTHON_IMAGE} AS runtime

ARG CYBERCONTROL_SOURCE_SHA=unknown
ARG CYBERCONTROL_SOURCE_TREE=unknown
ARG CYBERCONTROL_PRODUCT_SOURCE_SHA=unknown
ARG CYBERCONTROL_ENGINEERING_BASELINE_SHA=unknown
ARG CYBERCONTROL_PROCESS_VERSION=unknown
ARG SOURCE_DATE_EPOCH=0

ADD --checksum=sha256:e070f30274a4048dabeffc7bd038df7467e18ff7ada2d1ff75f0da7158739e33 \
    https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/jemalloc-5.3.0-r6.apk \
    /tmp/locked-apks/jemalloc-5.3.0-r6.apk
ADD --checksum=sha256:393dcd32629f06d7d85409c272d142d0c082772d10b87ef55ee82f47de3be637 \
    https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/libgcc-15.2.0-r5.apk \
    /tmp/locked-apks/libgcc-15.2.0-r5.apk
ADD --checksum=sha256:14c987b556f5385a5db18376e788c75f37d85321b8dc1920d926ea7daac1d6f6 \
    https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/libstdc++-15.2.0-r5.apk \
    /tmp/locked-apks/libstdc++-15.2.0-r5.apk

LABEL org.opencontainers.image.revision=${CYBERCONTROL_SOURCE_SHA} \
    com.cybercontrol.source-tree=${CYBERCONTROL_SOURCE_TREE} \
    com.cybercontrol.product-source=${CYBERCONTROL_PRODUCT_SOURCE_SHA} \
    com.cybercontrol.engineering-baseline=${CYBERCONTROL_ENGINEERING_BASELINE_SHA} \
    com.cybercontrol.process-version=${CYBERCONTROL_PROCESS_VERSION}

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LIYAN_REPOSITORY_ROOT=/app

RUN printf '%s  %s\n' \
        e070f30274a4048dabeffc7bd038df7467e18ff7ada2d1ff75f0da7158739e33 \
        /tmp/locked-apks/jemalloc-5.3.0-r6.apk \
        393dcd32629f06d7d85409c272d142d0c082772d10b87ef55ee82f47de3be637 \
        /tmp/locked-apks/libgcc-15.2.0-r5.apk \
        14c987b556f5385a5db18376e788c75f37d85321b8dc1920d926ea7daac1d6f6 \
        /tmp/locked-apks/libstdc++-15.2.0-r5.apk \
        > /tmp/locked-apks/SHA256SUMS \
    && sha256sum -c /tmp/locked-apks/SHA256SUMS \
    && apk add --no-network --allow-untrusted \
        /tmp/locked-apks/libgcc-15.2.0-r5.apk \
        /tmp/locked-apks/libstdc++-15.2.0-r5.apk \
        /tmp/locked-apks/jemalloc-5.3.0-r6.apk \
    && rm -f /var/log/apk.log \
    && rm -rf /tmp/locked-apks \
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
