#!/usr/bin/env bash
set -euo pipefail

namespace=openstack
release=octavia-valkey
secret=octavia-valkey-auth

kubectl -n "${namespace}" rollout status \
  statefulset/valkey-node --timeout=5m

password=$(
  kubectl -n "${namespace}" get secret "${secret}" \
    -o jsonpath='{.data.password}' | base64 -d
)
trap 'unset password' EXIT

pods=$(
  kubectl -n "${namespace}" get pod \
    -l "app.kubernetes.io/instance=${release}" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
)
test "$(printf '%s\n' "${pods}" | sed '/^$/d' | wc -l)" -eq 3

while IFS= read -r pod; do
  test -n "${pod}" || continue
  kubectl -n "${namespace}" exec "${pod}" -c sentinel -- \
    valkey-cli -p 26379 PING | grep -qx PONG
done <<<"${pods}"

first_pod=$(printf '%s\n' "${pods}" | sed '/^$/d' | head -1)
master=$(
  kubectl -n "${namespace}" exec "${first_pod}" -c sentinel -- \
    valkey-cli -p 26379 \
    SENTINEL get-master-addr-by-name octavia-jobboard
)
test -n "${master}"
printf 'Sentinel master:\n%s\n' "${master}"

kubectl -n "${namespace}" exec "${first_pod}" -c valkey -- \
  valkey-cli -a "${password}" --no-auth-warning PING | grep -qx PONG
