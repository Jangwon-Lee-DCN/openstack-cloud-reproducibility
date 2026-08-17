FROM python:3.12.11-slim@sha256:27f90d79cc85e9b7b2560063ef44fa0e9eaae7a7c3f5a9f74563065c5477cc24
WORKDIR /app
COPY pyproject.toml ./
COPY dcn_loki_gateway ./dcn_loki_gateway
RUN pip install --no-cache-dir .
USER 65532:65532
ENTRYPOINT ["uvicorn", "dcn_loki_gateway.app:app", "--host", "0.0.0.0", "--port", "8080"]
