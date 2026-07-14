FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY packages/contracts-python /app/packages/contracts-python
COPY backend /app/backend
COPY config /app/config

RUN python -m pip install --upgrade pip \
    && python -m pip install /app/packages/contracts-python /app/backend

WORKDIR /app/backend
EXPOSE 8000

CMD ["uvicorn", "liyans.main:app", "--host", "0.0.0.0", "--port", "8000"]
