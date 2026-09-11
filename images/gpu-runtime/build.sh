#!/usr/bin/env bash
set -euo pipefail

profile=${1:?profile required}
output_dir=${2:?output directory required}
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
manifest=$root/profiles.json
nccl_manifest=$root/nccl-packages.json
result_file=${RESULT_FILE:?RESULT_FILE required}
base_cache=${DCN_GPU_BASE_CACHE:?DCN_GPU_BASE_CACHE required}
for command in curl python3 qemu-img sha256sum virt-customize; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done

readarray -t values < <(python3 - "$manifest" "$nccl_manifest" "$profile" <<'PY'
import json, shlex, sys
p=json.load(open(sys.argv[1]))[sys.argv[3]]
n=json.load(open(sys.argv[2]))[sys.argv[3]]
for key in ("base_url", "base_sha256", "ubuntu", "cuda_package", "cudnn_package", "driver_package"):
    print(shlex.quote(p[key]))
print(shlex.quote(n))
PY
)
(( ${#values[@]} == 7 )) || { echo "unknown profile: $profile" >&2; exit 2; }
eval "base_url=${values[0]} base_sha256=${values[1]} ubuntu=${values[2]} cuda_package=${values[3]} cudnn_package=${values[4]} driver_package=${values[5]} nccl_version=${values[6]}"
mkdir -p "$output_dir"
mkdir -p "$base_cache"
base=$base_cache/$base_sha256.qcow2
image=$output_dir/$profile.qcow2
if [[ ! -f "$base" ]]; then
  curl --fail --location --retry 4 --output "$base.partial" "$base_url"
  printf '%s  %s\n' "$base_sha256" "$base.partial" | sha256sum --check --status
  mv "$base.partial" "$base"
fi
printf '%s  %s\n' "$base_sha256" "$base" | sha256sum --check --status
cp --reflink=auto "$base" "$image"
qemu-img resize "$image" 32G
repo=ubuntu${ubuntu/./}
virt-customize -a "$image" --network \
  --run-command 'rm -f /etc/machine-id; touch /etc/machine-id' \
  --run-command "ip link set eth0 up; ip address replace 169.254.2.15/16 dev eth0; ip route replace default via 169.254.2.2 dev eth0; rm -f /etc/resolv.conf; printf 'nameserver 169.254.2.3\\n' > /etc/resolv.conf" \
  --run-command "curl -fsSLo /tmp/cuda-keyring.deb https://developer.download.nvidia.com/compute/cuda/repos/$repo/x86_64/cuda-keyring_1.1-1_all.deb" \
  --run-command 'dpkg -i /tmp/cuda-keyring.deb && apt-get update' \
  --run-command "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends '$driver_package' '$cuda_package' '$cudnn_package' 'libnccl2=$nccl_version' 'libnccl-dev=$nccl_version' nvidia-container-toolkit" \
  --run-command "printf '%s\n' 'profile=$profile' 'cuda_package=$cuda_package' 'cudnn_package=$cudnn_package' 'nccl_version=$nccl_version' 'driver_package=$driver_package' > /etc/dcn-gpu-runtime-release" \
  --run-command 'ln -sfn ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf' \
  --run-command 'apt-get clean; rm -rf /var/lib/apt/lists/* /tmp/cuda-keyring.deb /var/lib/cloud/*'
qemu-img convert -p -O qcow2 -c "$image" "$image.compacted"
mv "$image.compacted" "$image"
digest=$(sha256sum "$image" | awk '{print $1}')
printf '%s=%s@sha256:%s\n' "${profile//[-.]/_}" "$image" "$digest" >"$result_file"
