ARG PYTHON_IMAGE=cybercontrol/gate-c-base-python:3.11@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4

FROM ${PYTHON_IMAGE}

ARG CYBERCONTROL_SOURCE_SHA=unknown
ARG CYBERCONTROL_SOURCE_TREE=unknown
ARG CYBERCONTROL_PRODUCT_SOURCE_SHA=unknown
ARG CYBERCONTROL_ENGINEERING_BASELINE_SHA=unknown
ARG CYBERCONTROL_PROCESS_VERSION=unknown

COPY third_party/gate-c-build/apk/libcrypto3-3.5.8-r0.apk \
    third_party/gate-c-build/apk/libssl3-3.5.8-r0.apk \
    /tmp/locked-apks/

LABEL org.opencontainers.image.revision=${CYBERCONTROL_SOURCE_SHA} \
    com.cybercontrol.source-tree=${CYBERCONTROL_SOURCE_TREE} \
    com.cybercontrol.product-source=${CYBERCONTROL_PRODUCT_SOURCE_SHA} \
    com.cybercontrol.engineering-baseline=${CYBERCONTROL_ENGINEERING_BASELINE_SHA} \
    com.cybercontrol.process-version=${CYBERCONTROL_PROCESS_VERSION}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8090

RUN printf '%s  %s\n' \
        161223a16f042b8e469e9441291e071464fd91d4f4bbe6f496ee8d0abd4e0701 \
        /tmp/locked-apks/libcrypto3-3.5.8-r0.apk \
        aca521e5ae4a321322a9d47ed64a1775f5ab1ffd215d1e9fc0433c58f7bfd037 \
        /tmp/locked-apks/libssl3-3.5.8-r0.apk \
        > /tmp/locked-apks/SHA256SUMS \
    && sha256sum -c /tmp/locked-apks/SHA256SUMS \
    && apk add --no-network --allow-untrusted \
        /tmp/locked-apks/libcrypto3-3.5.8-r0.apk \
        /tmp/locked-apks/libssl3-3.5.8-r0.apk \
    && rm -f /var/log/apk.log \
    && rm -rf /tmp/locked-apks \
    && python -m pip uninstall --yes setuptools wheel \
    && python -m pip uninstall --yes pip \
    && addgroup -S -g 10002 fixture \
    && adduser -S -D -H -u 10002 -G fixture -h /srv/fixture -s /sbin/nologin fixture \
    && mkdir -p /srv/fixture \
    && chown -R fixture:fixture /srv/fixture

COPY --chown=fixture:fixture infra/mock-provider/server.py /srv/fixture/server.py

WORKDIR /srv/fixture
USER 10002:10002
EXPOSE 8090

HEALTHCHECK --interval=10s --timeout=3s --start-period=3s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health/ready', timeout=2)"]

CMD ["python", "/srv/fixture/server.py"]
