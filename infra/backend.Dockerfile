ARG PYTHON_IMAGE=cybercontrol/gate-c-base-python:3.11@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4

FROM ${PYTHON_IMAGE} AS builder

ARG SOURCE_DATE_EPOCH=0
ENV UV_NO_NETWORK=1 \
    UV_LINK_MODE=copy
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}

WORKDIR /app
COPY third_party/gate-c-build/sources/uv-0.11.28-x86_64-unknown-linux-musl.tar.gz /tmp/uv.tar.gz
RUN tar -xzf /tmp/uv.tar.gz -C /tmp \
    && install -m 0555 /tmp/uv-x86_64-unknown-linux-musl/uv /usr/local/bin/uv \
    && rm -rf /tmp/uv.tar.gz /tmp/uv-x86_64-unknown-linux-musl \
    && uv --version | grep -q '^uv 0\.11\.28 '
COPY third_party/gate-c-build/python-wheelhouse /opt/cybercontrol/wheelhouse

COPY pyproject.toml uv.lock .python-version /app/
COPY backend /app/backend
COPY packages/contracts-python /app/packages/contracts-python

RUN python -m pip install --no-index --find-links /opt/cybercontrol/wheelhouse \
        hatchling==1.27.0 \
    && mkdir -p /tmp/workspace-wheels \
    && python -m pip wheel --no-index --no-deps --no-build-isolation \
        --wheel-dir /tmp/workspace-wheels \
        /app/packages/contracts-python /app/backend \
    && uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python --offline --no-index \
        --find-links /opt/cybercontrol/wheelhouse \
        --requirements /opt/cybercontrol/wheelhouse/backend-retrieval-requirements.txt \
    && uv pip install --python /app/.venv/bin/python --offline --no-index \
        --no-deps /tmp/workspace-wheels/*.whl \
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

COPY third_party/gate-c-build/apk/jemalloc-5.3.0-r6.apk \
    third_party/gate-c-build/apk/libgcc-15.2.0-r5.apk \
    third_party/gate-c-build/apk/libstdc++-15.2.0-r5.apk \
    /tmp/locked-apks/

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
