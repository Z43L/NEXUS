# The API runs as the authenticated, loopback-published client entrypoint.
FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY nexus/api/requirements-h0.lock /tmp/requirements-h0.lock
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes \
      -r /tmp/requirements-h0.lock \
    && groupadd --gid 10002 nexus-api \
    && useradd --uid 10002 --gid nexus-api --no-create-home --shell /usr/sbin/nologin nexus-api

COPY nexus/api/core /app/nexus/api/core
USER 10002:10002
EXPOSE 8000
ENTRYPOINT ["python", "-m", "uvicorn", "nexus.api.core.api_server:app"]
