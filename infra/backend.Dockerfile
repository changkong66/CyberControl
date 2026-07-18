ARG PYTHON_IMAGE=python:3.11-alpine@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4

FROM ${PYTHON_IMAGE} AS builder

ARG UV_VERSION=0.11.28
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

WORKDIR /app
RUN python -m pip install "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock .python-version /app/
COPY backend /app/backend
COPY packages/contracts-python /app/packages/contracts-python

RUN uv sync --frozen --no-dev --all-packages --no-editable --extra retrieval

FROM ${PYTHON_IMAGE} AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LIYAN_REPOSITORY_ROOT=/app

RUN python -m pip uninstall --yes setuptools wheel \
    && python -m pip uninstall --yes pip \
    && addgroup -S -g 10001 liyans \
    && adduser -S -D -H -u 10001 -G liyans -h /app -s /sbin/nologin liyans \
    && mkdir -p /app/backend /app/config /app/var/artifacts \
        /var/lib/liyans/artifacts /var/lib/liyans/audit \
    && chown -R liyans:liyans /app /var/lib/liyans

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
