#!/usr/bin/env bash
set -euo pipefail

namespace=openstack
daemonset=vpc-endpoint-agent
expected_cidrs=${VPC_ENDPOINT_SERVICE_CIDRS:-192.168.21.0/24}
expected_facade=${VPC_ENDPOINT_POLICY_FACADE_URL:-}

desired=$(kubectl -n "$namespace" get daemonset "$daemonset" -o jsonpath='{.status.desiredNumberScheduled}')
ready=$(kubectl -n "$namespace" get daemonset "$daemonset" -o jsonpath='{.status.numberReady}')
[[ "$desired" -gt 0 && "$ready" == "$desired" ]] || { echo "endpoint agent DaemonSet is not fully ready" >&2; exit 1; }
image=$(kubectl -n "$namespace" get daemonset "$daemonset" -o jsonpath='{.spec.template.spec.containers[0].image}')
[[ "$image" == *@sha256:* ]] || { echo "endpoint agent image is not digest-pinned" >&2; exit 1; }
args=$(kubectl -n "$namespace" get daemonset "$daemonset" -o jsonpath='{.spec.template.spec.containers[0].args}')
[[ "$args" == *"--allowed-service-cidrs=${expected_cidrs}"* ]] || { echo "endpoint service CIDRs differ from the approved value" >&2; exit 1; }
if [[ -n "$expected_facade" ]]; then
  [[ "$args" == *"--policy-facade-url=${expected_facade}"* ]] || { echo "endpoint policy facade URL differs from the approved value" >&2; exit 1; }
fi
for target in openstack/vpc-endpoint-policy-hmac vpc-control-plane-system/vpc-endpoint-policy-hmac; do
  ns=${target%/*}; secret=${target#*/}
  length=$(kubectl -n "$ns" get secret "$secret" -o jsonpath='{.data.hmac-secret}' | base64 -d | wc -c)
  [[ "$length" -ge 32 ]] || { echo "$target is missing or short" >&2; exit 1; }
done
kubectl auth can-i --as=system:serviceaccount:openstack:vpc-endpoint-agent list vpcendpoints.vpc.dcn.ssu.ac.kr --all-namespaces | grep -qx yes
kubectl auth can-i --as=system:serviceaccount:openstack:vpc-endpoint-agent create leases.coordination.k8s.io -n openstack | grep -qx yes
echo "vpc-endpoint-agent-verification-ok desired=${desired} image=${image}"
