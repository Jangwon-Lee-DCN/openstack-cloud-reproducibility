#!/usr/bin/env bash
set -euo pipefail

namespace=${NAMESPACE:-openstack}
device=${IRONIC_PROVISIONING_INTERFACE:-dcn-ironic0}
expected_address=${IRONIC_PROVISIONING_ADDRESS:-10.64.111.2/24}

kubectl -n "$namespace" wait --for=condition=ready pod/ironic-conductor-0 --timeout=10m
test "$(kubectl -n "$namespace" get statefulset ironic-conductor -o jsonpath='{.spec.replicas}')" = 1
kubectl -n "$namespace" exec ironic-conductor-0 -c ironic-conductor -- \
  ip -4 address show dev "$device" | grep -F "inet $expected_address"
kubectl -n "$namespace" exec ironic-conductor-0 -c ironic-conductor-pxe -- \
  sh -ec "grep -q ':0045 ' /proc/net/udp /proc/net/udp6"
kubectl -n "$namespace" exec ironic-conductor-0 -c ironic-conductor-http -- \
  sh -ec "grep -q ':1F90 ' /proc/net/tcp /proc/net/tcp6"

config=$(kubectl -n "$namespace" exec ironic-conductor-0 -c ironic-conductor -- \
  awk -F ' *= *' '
    /^\[conductor\]$/ { section="conductor"; next }
    /^\[deploy\]$/ { section="deploy"; next }
    /^\[/ { section=""; next }
    section == "conductor" && $1 == "automated_clean" { print "automated_clean=" $2 }
    section == "conductor" && $1 == "api_url" { print "api_url=" $2 }
    section == "deploy" && $1 == "http_url" { print "http_url=" $2 }
  ' /etc/ironic/ironic.conf)
grep -Fx 'automated_clean=false' <<<"$config"
grep -Fx 'api_url=https://internal.cloud.dcn.ssu.ac.kr/baremetal' <<<"$config"
grep -Fx 'http_url=http://10.64.111.2:8080' <<<"$config"

echo 'Ironic physical provisioning runtime verified'
