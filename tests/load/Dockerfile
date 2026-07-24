ARG PYTHON_IMAGE=python:3.11-alpine@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4

FROM ${PYTHON_IMAGE} AS builder

ARG UV_VERSION=0.11.28
ENV UV_LINK_MODE=copy
WORKDIR /app
RUN python -m pip install "uv==${UV_VERSION}"
COPY pyproject.toml uv.lock .python-version /app/
COPY backend /app/backend
COPY packages/contracts-python /app/packages/contracts-python
RUN uv sync --frozen --no-dev --all-packages --no-editable --extra load

FROM ${PYTHON_IMAGE} AS runtime

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
