FROM alpine/helm:3.18.4@sha256:e7ecbf4a200dea73d64bfb8cb0936829164945f2b4d02a0274093073ee8d264f AS helm

FROM debian:bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818 AS tools
ARG KPT_VERSION=v1.0.0-beta.62.1
ARG KPT_SHA256=e739cd7695a5fe678c26b29da57977f17921c0d2c5f1b200f7a1ed50e10a28be
ARG PORCH_VERSION=1.5.7
ARG PORCHCTL_ARCHIVE_SHA256=61a50b7512a0accf84074e20c3d82a335b2e5b08f1ffba706bb3f712c68ebd0f
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tar \
 && curl -fsSLo /tmp/kpt \
      "https://github.com/kptdev/kpt/releases/download/${KPT_VERSION}/kpt_linux_amd64" \
 && echo "${KPT_SHA256}  /tmp/kpt" | sha256sum -c - \
 && curl -fsSLo /tmp/porchctl.tar.gz \
      "https://github.com/nephio-project/porch/releases/download/v${PORCH_VERSION}/porchctl_${PORCH_VERSION}_linux_amd64.tar.gz" \
 && echo "${PORCHCTL_ARCHIVE_SHA256}  /tmp/porchctl.tar.gz" | sha256sum -c - \
 && tar -xzf /tmp/porchctl.tar.gz -C /tmp \
 && mkdir -p /out \
 && install -m 0755 /tmp/kpt /out/kpt \
 && install -m 0755 /tmp/porchctl /out/porchctl

FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 65532 writer
COPY --from=helm /usr/bin/helm /usr/local/bin/helm
COPY --from=tools /out/kpt /out/porchctl /usr/local/bin/
WORKDIR /app
COPY magnum-driver/ /app/magnum-driver/
COPY --chmod=0644 repository-writer/server.py /app/repository-writer/server.py
COPY vendor/capi-helm-charts/openstack-cluster/ /app/vendor/capi-helm-charts/openstack-cluster/
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["python3", "/app/repository-writer/server.py"]
