#!/usr/bin/env bash
set -euo pipefail

daemonset=vpc-metadata-attestor
desired=$(kubectl -n openstack get daemonset "$daemonset" -o jsonpath='{.status.desiredNumberScheduled}')
ready=$(kubectl -n openstack get daemonset "$daemonset" -o jsonpath='{.status.numberReady}')
[[ "$desired" -ge 6 && "$ready" == "$desired" ]] || { echo "$daemonset is not fully ready" >&2; exit 1; }
image=$(kubectl -n openstack get daemonset "$daemonset" -o jsonpath='{.spec.template.spec.containers[0].image}')
[[ "$image" == *@sha256:* ]] || { echo "$daemonset image is not digest-pinned" >&2; exit 1; }

attestor_key=$(kubectl -n openstack get secret vpc-metadata-attestor-secrets -o jsonpath='{.data.vpc-instance-identity-hmac-secret}')
facade_key=$(kubectl -n vpc-control-plane-system get secret vpc-instance-identity -o jsonpath='{.data.hmac-secret}')
[[ "$attestor_key" == "$facade_key" ]] || { echo "attestor and facade identity HMAC secrets differ" >&2; exit 1; }
length=$(printf %s "$attestor_key" | base64 -d | wc -c)
[[ "$length" -ge 32 ]] || { echo "instance identity HMAC secret is short" >&2; exit 1; }

configured=$(kubectl -n openstack get secret neutron-ovn-metadata-agent-default -o jsonpath='{.data.ovn_metadata_agent\.ini}' | base64 -d |
  python3 -c 'import configparser,sys; c=configparser.ConfigParser(); c.read_file(sys.stdin); print(c["DEFAULT"].get("nova_metadata_host", ""))')
[[ "$configured" == vpc-metadata-attestor.openstack.svc.cluster.local ]] || { echo "OVN metadata agent is not using the attestor" >&2; exit 1; }

kubectl -n openstack get networkpolicy vpc-metadata-attestor-ingress >/dev/null
# A normal readiness probe cannot detect policy rejection of hostNetwork
# clients. Prove the exact metadata-agent-to-attestor path on every node.
for pod in $(kubectl -n openstack get pod -l application=neutron,component=ovn-metadata-agent -o name); do
  kubectl -n openstack exec "$pod" -c neutron-ovn-metadata-agent -- python3 -c \
    'import socket; s=socket.create_connection(("vpc-metadata-attestor.openstack.svc.cluster.local",8775),5); s.close()'
done
kubectl -n vpc-control-plane-system get networkpolicy vpc-facade-default-deny >/dev/null
automount=$(kubectl -n openstack get daemonset "$daemonset" -o jsonpath='{.spec.template.spec.automountServiceAccountToken}')
[[ "$automount" == false ]] || { echo "$daemonset must not mount a Kubernetes API token" >&2; exit 1; }
echo "vpc-instance-identity-verification-ok ready=${ready}/${desired} image=${image}"
