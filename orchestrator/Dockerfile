# syntax=docker/dockerfile:1.7

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

ARG UV_VERSION=0.12.18

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    ORCHESTRATOR_ROLE=api \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

COPY config.toml ./config.toml
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/healthcheck.sh /healthcheck.sh

RUN chmod +x /entrypoint.sh /healthcheck.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD /healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]
