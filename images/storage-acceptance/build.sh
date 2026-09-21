#!/usr/bin/env bash
set -euo pipefail

component=${1:?component required}
output_dir=${2:?output directory required}
[[ $component == ubuntu-24.04-storage-acceptance ]] || { echo "unsupported component: $component" >&2; exit 2; }
result_file=${RESULT_FILE:?RESULT_FILE required}
base_cache=${DCN_GPU_BASE_CACHE:?DCN_GPU_BASE_CACHE required}
base_url=https://cloud-images.ubuntu.com/releases/noble/release-20260801/ubuntu-24.04-server-cloudimg-amd64.img
base_sha256=0533b0655c32e68b31d792ecd6ccfca95abdbc536c4446874fe0513bd4140ffe

for command in curl qemu-img sha256sum virt-customize; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done
mkdir -p "$output_dir" "$base_cache"
base=$base_cache/$base_sha256.qcow2
image=$output_dir/$component.qcow2
if [[ ! -f $base ]]; then
  curl --fail --location --retry 4 --output "$base.partial" "$base_url"
  printf '%s  %s\n' "$base_sha256" "$base.partial" | sha256sum --check --status
  mv "$base.partial" "$base"
fi
printf '%s  %s\n' "$base_sha256" "$base" | sha256sum --check --status
cp --reflink=auto "$base" "$image"

guest_network="ip link set eth0 up; ip address replace 169.254.2.15/16 dev eth0; ip route replace default via 169.254.2.2 dev eth0; rm -f /etc/resolv.conf; printf 'nameserver 169.254.2.3\\n' > /etc/resolv.conf"
virt-customize -a "$image" --network --memsize 2048 --smp 4 \
  --run-command 'rm -f /etc/machine-id; touch /etc/machine-id' \
  --run-command "$guest_network; apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends fio qemu-guest-agent; command -v fio >/dev/null; dpkg-query -W qemu-guest-agent >/dev/null" \
  --run-command "printf '%s\n' 'component=$component' 'base_sha256=$base_sha256' > /etc/dcn-storage-acceptance-release" \
  --run-command 'ln -sfn ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf' \
  --run-command 'apt-get clean; rm -rf /var/lib/apt/lists/* /var/lib/cloud/*'
qemu-img check "$image"
qemu-img convert -p -O qcow2 -c "$image" "$image.compacted"
mv "$image.compacted" "$image"
digest=$(sha256sum "$image" | awk '{print $1}')
printf '%s=%s@sha256:%s\n' "${component//[-.]/_}" "$image" "$digest" >"$result_file"
