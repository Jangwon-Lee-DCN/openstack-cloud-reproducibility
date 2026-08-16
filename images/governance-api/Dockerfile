FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7

ARG SOURCE_COMMIT=unknown
LABEL org.opencontainers.image.source="openstack-production-datacenter" \
      org.opencontainers.image.revision="$SOURCE_COMMIT"

RUN groupadd --gid 65532 governance && useradd --uid 65532 --gid 65532 --no-create-home governance
COPY services/governance-api /src
RUN pip install --no-cache-dir /src && rm -rf /src
USER 65532:65532
WORKDIR /var/lib/governance
EXPOSE 8080
ENTRYPOINT ["dcn-governance-api"]
