# Pin the multi-platform manifest digest so Docker builds do not change when
# the upstream tag is refreshed. Update deliberately after image/CVE review.
FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/nexus-h1-node:/app/nexus/h0

WORKDIR /app

# The worker and Router share only the pinned cryptography dependency. Keep the
# runtime small and install binary wheels only (no compiler/build toolchain).
COPY requirements-cryptography.lock /tmp/requirements-cryptography.lock
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: \
      -r /tmp/requirements-cryptography.lock \
    && groupadd --gid 10001 nexus \
    && useradd --uid 10001 --gid nexus --no-create-home --shell /usr/sbin/nologin nexus

COPY nexus/h0/router.py nexus/h0/nexus_common.py /app/nexus/h0/
COPY nexus-h1-node/worker2.py nexus-h1-node/jwt_auth.py \
     nexus-h1-node/container_healthcheck.py /app/nexus-h1-node/

USER 10001:10001
ENTRYPOINT ["python"]
