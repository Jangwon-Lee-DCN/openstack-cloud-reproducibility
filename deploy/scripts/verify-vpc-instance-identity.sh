#!/usr/bin/env bash
set -euo pipefail

deployment=vpc-metadata-attestor
desired=$(kubectl -n openstack get deployment "$deployment" -o jsonpath='{.spec.replicas}')
ready=$(kubectl -n openstack get deployment "$deployment" -o jsonpath='{.status.readyReplicas}')
[[ "$desired" -ge 2 && "$ready" == "$desired" ]] || { echo "$deployment is not fully ready" >&2; exit 1; }
image=$(kubectl -n openstack get deployment "$deployment" -o jsonpath='{.spec.template.spec.containers[0].image}')
[[ "$image" == *@sha256:* ]] || { echo "$deployment image is not digest-pinned" >&2; exit 1; }

attestor_key=$(kubectl -n openstack get secret vpc-metadata-attestor-secrets -o jsonpath='{.data.vpc-instance-identity-hmac-secret}')
facade_key=$(kubectl -n vpc-control-plane-system get secret vpc-instance-identity -o jsonpath='{.data.hmac-secret}')
[[ "$attestor_key" == "$facade_key" ]] || { echo "attestor and facade identity HMAC secrets differ" >&2; exit 1; }
length=$(printf %s "$attestor_key" | base64 -d | wc -c)
[[ "$length" -ge 32 ]] || { echo "instance identity HMAC secret is short" >&2; exit 1; }

configured=$(kubectl -n openstack get secret neutron-ovn-metadata-agent-default -o jsonpath='{.data.ovn_metadata_agent\.ini}' | base64 -d |
  python3 -c 'import configparser,sys; c=configparser.ConfigParser(); c.read_file(sys.stdin); print(c["DEFAULT"].get("nova_metadata_host", ""))')
[[ "$configured" == vpc-metadata-attestor.openstack.svc.cluster.local ]] || { echo "OVN metadata agent is not using the attestor" >&2; exit 1; }

kubectl -n openstack get networkpolicy vpc-metadata-attestor-ingress >/dev/null
kubectl -n vpc-control-plane-system get networkpolicy vpc-facade-default-deny >/dev/null
automount=$(kubectl -n openstack get deployment "$deployment" -o jsonpath='{.spec.template.spec.automountServiceAccountToken}')
[[ "$automount" == false ]] || { echo "$deployment must not mount a Kubernetes API token" >&2; exit 1; }
echo "vpc-instance-identity-verification-ok ready=${ready}/${desired} image=${image}"
