FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    ORCHESTRATOR_ROLE=api \
    PYTHONPATH=/app/src

WORKDIR /app

COPY pyproject.toml ./
RUN python - <<'PY' > /tmp/requirements.txt
from pathlib import Path
import tomllib

pyproject = tomllib.loads(Path("pyproject.toml").read_text())
for dependency in pyproject["project"]["dependencies"]:
    print(dependency)
PY
RUN pip install -r /tmp/requirements.txt

COPY src ./src
RUN pip install --no-deps .

COPY config.toml ./config.toml
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/healthcheck.sh /healthcheck.sh

RUN chmod +x /entrypoint.sh /healthcheck.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD /healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]
