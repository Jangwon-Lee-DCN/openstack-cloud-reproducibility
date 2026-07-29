#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

sudo install -o root -g root -m 0644 \
  "${script_dir}/99-kubernetes-inotify.conf" \
  /etc/sysctl.d/99-kubernetes-inotify.conf
sudo install -o root -g root -m 0644 \
  "${script_dir}/70-openstack-kvm.rules" \
  /etc/udev/rules.d/70-openstack-kvm.rules

sudo sysctl --system
sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=/dev/kvm

test "$(stat -c '%a' /dev/kvm)" = "666"
