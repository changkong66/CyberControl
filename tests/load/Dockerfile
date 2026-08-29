ARG PYTHON_IMAGE=cybercontrol/gate-c-base-python:3.11@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4

FROM ${PYTHON_IMAGE} AS builder

ARG SOURCE_DATE_EPOCH=0
ENV UV_NO_NETWORK=1 \
    UV_LINK_MODE=copy \
    SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}
WORKDIR /app
COPY third_party/gate-c-build/sources/uv-0.11.28-x86_64-unknown-linux-musl.tar.gz /tmp/uv.tar.gz
RUN tar -xzf /tmp/uv.tar.gz -C /tmp \
    && install -m 0555 /tmp/uv-x86_64-unknown-linux-musl/uv /usr/local/bin/uv \
    && rm -rf /tmp/uv.tar.gz /tmp/uv-x86_64-unknown-linux-musl \
    && uv --version | grep -q '^uv 0\.11\.28 '
COPY third_party/gate-c-build/python-wheelhouse /opt/cybercontrol/wheelhouse
RUN sed -e '/^zope-interface==8.5/,/# via gevent/d' \
      /opt/cybercontrol/wheelhouse/gate-c-load-requirements.txt \
      > /tmp/gate-c-load-linux-requirements.txt
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
        --requirements /tmp/gate-c-load-linux-requirements.txt \
    && uv pip install --python /app/.venv/bin/python --offline --no-index \
        --no-deps /opt/cybercontrol/wheelhouse/zope_interface-8.5-cp311-cp311-linux_x86_64.whl \
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

LABEL org.opencontainers.image.revision=${CYBERCONTROL_SOURCE_SHA} \
    com.cybercontrol.source-tree=${CYBERCONTROL_SOURCE_TREE} \
    com.cybercontrol.product-source=${CYBERCONTROL_PRODUCT_SOURCE_SHA} \
    com.cybercontrol.engineering-baseline=${CYBERCONTROL_ENGINEERING_BASELINE_SHA} \
    com.cybercontrol.process-version=${CYBERCONTROL_PROCESS_VERSION}

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/tests/load \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN addgroup -S -g 10003 gatec \
    && adduser -S -D -H -u 10003 -G gatec -h /app -s /sbin/nologin gatec \
    && mkdir -p /app/tests/load /results \
    && chown -R gatec:gatec /app /results
COPY --from=builder --chown=gatec:gatec /app/.venv /app/.venv
COPY --chown=gatec:gatec tests/load /app/tests/load
COPY --chown=gatec:gatec data/topic1 /app/data/topic1
WORKDIR /app
USER 10003:10003
CMD ["locust", "-f", "/app/tests/load/locustfile.py"]
