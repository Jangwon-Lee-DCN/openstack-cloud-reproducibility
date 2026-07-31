#!/usr/bin/env bash
set -euo pipefail

OUTPUT_DIR=${AMPHORA_OUTPUT_DIR:-/home/ubuntu/amphora-build-output}
OUTPUT_NAME=${AMPHORA_OUTPUT_NAME:-amphora-x64-haproxy-ubuntu-noble-2026.1}
image=${OUTPUT_DIR}/${OUTPUT_NAME}.qcow2

qemu-img check "${image}"
qemu-img info --output=json "${image}"
sha256sum "${image}"

sudo -n virt-inspector -a "${image}" | grep -q '<distro>ubuntu</distro>'
sudo -n virt-cat -a "${image}" \
  /lib/systemd/system/amphora-agent.service | \
  grep -q '/usr/local/bin/amphora-agent'
sudo -n virt-ls -a "${image}" \
  /etc/systemd/system/multi-user.target.wants | \
  grep -qx 'amphora-agent.service'

if sudo -n virt-ls -a "${image}" \
    /etc/systemd/system/multi-user.target.wants | grep -q '^ssh'; then
  echo 'SSH boot unit is unexpectedly enabled' >&2
  exit 1
fi

sudo -n virt-cat -a "${image}" /etc/shadow | grep -q '^root:\*:'
echo 'Amphora image verification passed.'
