FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS driver

ARG MAGNUM_CAPI_HELM_VERSION=1.4.0

RUN pip install --no-cache-dir --no-deps --target /driver \
      "magnum-capi-helm==${MAGNUM_CAPI_HELM_VERSION}"

FROM docker.io/alpine/helm:3.18.4@sha256:e7ecbf4a200dea73d64bfb8cb0936829164945f2b4d02a0274093073ee8d264f AS helm

FROM quay.io/airshipit/magnum:2026.1-ubuntu_noble@sha256:99b90d03d3dbb26ebb768b64077661ceb8deee1d5fa48b07a6ffb459a7028da9

ARG MAGNUM_CAPI_HELM_VERSION=1.4.0

COPY --from=driver /driver/ /var/lib/openstack/lib/python3.12/site-packages/
COPY --from=helm /usr/bin/helm /usr/local/bin/helm

RUN /var/lib/openstack/bin/python /workspace/patch_token_file.py \
 && /var/lib/openstack/bin/python -c \
      "import importlib.metadata as m; assert m.version('magnum-capi-helm') == '${MAGNUM_CAPI_HELM_VERSION}'" \
 && helm version --short
