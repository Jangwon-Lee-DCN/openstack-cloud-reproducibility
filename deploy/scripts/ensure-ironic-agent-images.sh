#!/usr/bin/env bash
set -euo pipefail

namespace=${NAMESPACE:-openstack}
cache=${IRONIC_AGENT_CACHE:-/var/cache/dcn-ironic-agent}
client_image=${OPENSTACK_CLIENT_IMAGE:-quay.io/airshipit/openstack-client:2026.1-ubuntu_noble}
base=https://tarballs.openstack.org/ironic-python-agent/tinyipa/files
kernel=tinyipa-stable-2025.1.vmlinuz
ramdisk=tinyipa-stable-2025.1.gz
kernel_sha=15ed5220a397e6960a9ac6f770a07e3cc209c6870c42cbf8f388aa409d11ea71
ramdisk_sha=94396ea601016393f23eafecf8848f1f453274f93f1d1f4423f9355e4596926c
pod=ironic-agent-image-loader

mkdir -p "$cache"
for spec in "$kernel:$kernel_sha" "$ramdisk:$ramdisk_sha"; do
  file=${spec%%:*}
  expected=${spec#*:}
  if [[ ! -f "$cache/$file" ]] || ! echo "$expected  $cache/$file" | sha256sum -c - >/dev/null 2>&1; then
    curl --fail --location --retry 3 --connect-timeout 15 "$base/$file" -o "$cache/$file.part"
    echo "$expected  $cache/$file.part" | sha256sum -c -
    mv "$cache/$file.part" "$cache/$file"
  fi
done

kubectl -n "$namespace" delete pod "$pod" --ignore-not-found --wait=true >/dev/null
cleanup() { kubectl -n "$namespace" delete pod "$pod" --ignore-not-found --wait=false >/dev/null 2>&1 || true; }
trap cleanup EXIT
kubectl -n "$namespace" run "$pod" --restart=Never --image="$client_image" \
  --overrides='{"spec":{"containers":[{"name":"'$pod'","image":"'$client_image'","command":["sleep","900"],"envFrom":[{"secretRef":{"name":"ironic-keystone-admin"}}]}]}}' \
  --command -- sleep 900 >/dev/null
kubectl -n "$namespace" wait --for=condition=Ready pod/"$pod" --timeout=120s >/dev/null

ensure_image() {
  local name=$1 file=$2 disk=$3 container=$4 sha=$5 actual
  actual=$(kubectl -n "$namespace" exec "$pod" -- \
    openstack image show "$name" -f value -c properties 2>/dev/null || true)
  if grep -Fq "$sha" <<<"$actual"; then
    return
  fi
  if kubectl -n "$namespace" exec "$pod" -- openstack image show "$name" >/dev/null 2>&1; then
    echo "$name exists without the approved dcn_sha256; refusing replacement" >&2
    exit 1
  fi
  kubectl -n "$namespace" cp "$cache/$file" "$pod:/tmp/$file" -c "$pod"
  kubectl -n "$namespace" exec "$pod" -- openstack image create "$name" \
    --public --protected --disk-format "$disk" --container-format "$container" \
    --property "dcn_sha256=$sha" --file "/tmp/$file" >/dev/null
  kubectl -n "$namespace" exec "$pod" -- openstack image show "$name" \
    -f value -c status | grep -Fx active
}

ensure_image ironic-agent.kernel "$kernel" aki aki "$kernel_sha"
ensure_image ironic-agent.initramfs "$ramdisk" ari ari "$ramdisk_sha"
echo 'checksum-pinned Ironic agent images verified'
