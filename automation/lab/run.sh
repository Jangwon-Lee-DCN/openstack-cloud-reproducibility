#!/usr/bin/env bash
set -euo pipefail

action=${1:?usage: run.sh <create|status|inventory|destroy>}
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
namespace=${OPENSTACK_NAMESPACE:-openstack}
pod=${LAB_OSC_POD:-rebuild-lab-osc}
image=${LAB_OSC_IMAGE:-quay.io/airshipit/openstack-client:2026.1-ubuntu_noble}
secret=${LAB_OSC_SECRET:-horizon-keystone-admin}

case "$action" in
  create|status|inventory|destroy) ;;
  *) echo "unsupported action: $action" >&2; exit 2 ;;
esac

cleanup() {
  kubectl -n "$namespace" delete pod "$pod" \
    --grace-period=0 --force --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

kubectl -n "$namespace" delete pod "$pod" --ignore-not-found --wait=true >/dev/null
kubectl -n "$namespace" run "$pod" \
  --image="$image" --restart=Never \
  --overrides="{\"spec\":{\"containers\":[{\"name\":\"$pod\",\"image\":\"$image\",\"command\":[\"sleep\",\"1800\"],\"envFrom\":[{\"secretRef\":{\"name\":\"$secret\"}}]}]}}" \
  --command -- sleep 1800 >/dev/null
kubectl -n "$namespace" wait --for=condition=Ready "pod/$pod" --timeout=3m >/dev/null

public_key=""
if [[ "$action" == "create" ]]; then
  public_key_file=${LAB_PUBLIC_KEY_FILE:?set LAB_PUBLIC_KEY_FILE to an SSH public key}
  test -f "$public_key_file"
  public_key=$(<"$public_key_file")
fi

kubectl -n "$namespace" exec -i "$pod" -- env \
  "LAB_PUBLIC_KEY=$public_key" \
  "DELETE_LAB_IMAGE=${DELETE_LAB_IMAGE:-0}" \
  "UBUNTU_IMAGE_BASE_URL=${UBUNTU_IMAGE_BASE_URL:-https://cloud-images.ubuntu.com/releases/noble/release}" \
  bash -s -- "$action" < "$root/remote.sh"
