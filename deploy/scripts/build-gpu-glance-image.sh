#!/usr/bin/env bash
set -euo pipefail
umask 077

base=${1:?usage: build-gpu-glance-image.sh BASE_QCOW2 OUTPUT_QCOW2}
output=${2:?usage: build-gpu-glance-image.sh BASE_QCOW2 OUTPUT_QCOW2}
expected=${GPU_BASE_SHA256:?set GPU_BASE_SHA256 to the approved base image digest}
contract=${GPU_IMAGE_CONTRACT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/config/gpu-image-contract.yaml}

test -f "$base"
test ! -e "$output"
printf '%s  %s\n' "$expected" "$base" | sha256sum --check --status
command -v qemu-img >/dev/null
command -v virt-customize >/dev/null

readarray -t packages < <(python3 - "$contract" <<'PY'
import sys, yaml
value = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for name, version in value["packages"].items():
    print(f"{name}={version}")
PY
)
package_list=$(IFS=,; echo "${packages[*]}")

qemu-img convert -p -O qcow2 "$base" "$output"
trap 'rm -f -- "$output"' ERR
virt-customize -a "$output" \
  --network \
  --run-command 'apt-get update' \
  --install "$package_list" \
  --run-command 'apt-get clean' \
  --run-command 'rm -rf /var/lib/apt/lists/*' \
  --run-command 'systemctl enable cloud-init.service' \
  --selinux-relabel
qemu-img check "$output"
sha256sum "$output" >"$output.sha256"
printf 'built=%s\ncontract=%s\n' "$output" "$contract"
