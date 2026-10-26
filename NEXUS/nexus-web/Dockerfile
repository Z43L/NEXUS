FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY nexus-web/h0_local.py /app/h0_local.py
COPY nexus-web/h0.html /app/h0.html
USER 1000:1000
EXPOSE 8080
ENTRYPOINT ["python", "/app/h0_local.py"]
