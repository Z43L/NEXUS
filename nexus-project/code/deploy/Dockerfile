# Build from nexus-project/code:  docker build -f deploy/Dockerfile -t nexus-runtime .
FROM python:3.9-slim
WORKDIR /app
# stdlib-only by default; `cryptography` is an optional vetted-crypto fast path
RUN pip install --no-cache-dir cryptography==42.0.5 || true
COPY nexus_runtime ./nexus_runtime
COPY nexus_api ./nexus_api
COPY nexus_cli ./nexus_cli
COPY nexus_storage ./nexus_storage
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
RUN useradd -m nexus && mkdir /data && chown nexus /data
USER nexus
ENTRYPOINT ["python", "-m", "nexus_cli"]
