#!/usr/bin/env bash
set -euo pipefail

image=${1:?usage: smoke-test-glance-image.sh IMAGE NETWORK FLAVOR}
network=${2:?usage: smoke-test-glance-image.sh IMAGE NETWORK FLAVOR}
flavor=${3:?usage: smoke-test-glance-image.sh IMAGE NETWORK FLAVOR}
name="glance-image-smoke-$(date +%s)"
user_data=$(mktemp)
trap 'openstack server delete --wait "$name" >/dev/null 2>&1 || true; rm -f -- "$user_data"' EXIT
cat >"$user_data" <<'EOF'
#cloud-config
runcmd:
  - [sh, -c, 'echo DCN_GLANCE_IMAGE_SMOKE_OK >/dev/console']
EOF
openstack server create "$name" --image "$image" --flavor "$flavor" \
  --network "$network" --user-data "$user_data" --wait >/dev/null
status=$(openstack server show "$name" -f value -c status)
[[ $status == ACTIVE ]] || { echo "server status is $status" >&2; exit 1; }
for _ in $(seq 1 60); do
  if openstack console log show "$name" 2>/dev/null | grep -q DCN_GLANCE_IMAGE_SMOKE_OK; then
    echo "image smoke passed: $image"
    exit 0
  fi
  sleep 5
done
echo 'cloud-init console marker was not observed' >&2
exit 1
