FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
WORKDIR /app
COPY nexus/api/requirements-h0.lock /tmp/api.lock
COPY requirements-cryptography.lock /tmp/crypto.lock
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r /tmp/api.lock -r /tmp/crypto.lock
COPY nexus/api /app/nexus/api
