#!/usr/bin/env bash
set -euo pipefail

VERSION=v0.0.36
EXPECTED_SHA256=a5b4b057e4e400a2ca7188b03dc11303f874bfe600fc837d5446d86b3d13e26c
URL="https://raw.githubusercontent.com/rancher/local-path-provisioner/${VERSION}/deploy/local-path-storage.yaml"
REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
manifest=$(mktemp /tmp/local-path-storage.XXXXXX.yaml)
trap 'rm -f "$manifest"' EXIT

curl --fail --silent --show-error --location "$URL" --output "$manifest"
actual=$(sha256sum "$manifest" | awk '{print $1}')
[[ "$actual" == "$EXPECTED_SHA256" ]] || {
  echo "local-path-provisioner manifest checksum mismatch" >&2
  exit 1
}
kubectl apply -f "$manifest"
kubectl rollout status -n local-path-storage deployment/local-path-provisioner --timeout=5m
kubectl apply -f "$REPO_ROOT/deploy/manifests/dcn-local-storageclass.yaml"
