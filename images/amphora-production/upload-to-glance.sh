#!/usr/bin/env bash
set -euo pipefail

OUTPUT_DIR=${AMPHORA_OUTPUT_DIR:-/home/ubuntu/amphora-build-output}
OUTPUT_NAME=${AMPHORA_OUTPUT_NAME:-amphora-x64-haproxy-ubuntu-noble-2026.1}
GLANCE_IMAGE_NAME=${GLANCE_IMAGE_NAME:-amphora-x64-haproxy-ubuntu-noble-2026.1-$(date -u +%Y%m%d)}
image=${OUTPUT_DIR}/${OUTPUT_NAME}.qcow2

test -f "${image}"

openstack image create "${GLANCE_IMAGE_NAME}" \
  --private \
  --container-format bare \
  --disk-format qcow2 \
  --min-disk 2 \
  --min-ram 1024 \
  --tag amphora-candidate \
  --property hw_architecture=x86_64 \
  --property os_distro=ubuntu \
  --property os_version=24.04 \
  --file "${image}"

openstack image show "${GLANCE_IMAGE_NAME}" -f yaml
