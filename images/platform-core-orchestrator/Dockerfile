FROM docker.io/library/python:3.12.11-slim@sha256:47ae396f09c1303b8653019811a8498470603d7ffefc29cb07c88f1f8cb3d19f
WORKDIR /app
COPY core /app/core
COPY migrations /app/migrations
RUN useradd --uid 10001 --no-create-home core && mkdir /data && chown core:core /data
USER 10001
ENV PYTHONUNBUFFERED=1 CORE_DB_PATH=/data/core.db PORT=8080
EXPOSE 8080
ENTRYPOINT ["python", "-m", "core.http"]
