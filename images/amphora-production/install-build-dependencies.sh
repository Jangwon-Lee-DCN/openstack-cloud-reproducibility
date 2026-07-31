#!/usr/bin/env bash
set -euo pipefail

sudo -n apt-get update
sudo -n apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  debootstrap \
  dosfstools \
  e2fsprogs \
  gdisk \
  git \
  kpartx \
  qemu-utils \
  python3-pip \
  python3-venv \
  squashfs-tools \
  uuid-runtime

