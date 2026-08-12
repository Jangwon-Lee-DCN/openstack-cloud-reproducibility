#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
VPC_REPO=${VPC_CONTROL_PLANE_REPO:-$REPO_ROOT/../vpc-control-plane}
ATTESTOR_IMAGE=${METADATA_ATTESTOR_IMAGE:?set METADATA_ATTESTOR_IMAGE to an immutable @sha256 reference}
IMAGE_LOCK="$REPO_ROOT/deploy/locks/vpc-policy-images.yaml"
[[ "$ATTESTOR_IMAGE" == *@sha256:* ]] || { echo "metadata attestor image must be digest-pinned" >&2; exit 1; }
[[ ${APPROVE_VPC_IDENTITY_PATH:-} == yes ]] || {
  echo "Review the metadata cutover and set APPROVE_VPC_IDENTITY_PATH=yes." >&2
  exit 1
}

for command in kubectl helm python3 base64; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done
test -f "$VPC_REPO/config/production/metadata-attestor.yaml"
git -C "$VPC_REPO" diff --quiet && git -C "$VPC_REPO" diff --cached --quiet || { echo "refusing identity cutover from dirty VPC source" >&2; exit 1; }
locked_revision=$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["spec"]["sourceRevision"])' "$IMAGE_LOCK")
locked_image=$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["spec"].get("metadataAttestorImage", ""))' "$IMAGE_LOCK")
git -C "$VPC_REPO" merge-base --is-ancestor "$locked_revision" HEAD &&
  git -C "$VPC_REPO" diff --quiet "$locked_revision" HEAD -- . ':(exclude)config/production/kustomization.yaml' &&
  [[ "$ATTESTOR_IMAGE" == "$locked_image" ]] || { echo "metadata attestor image/source does not match the production VPC image lock" >&2; exit 1; }
kubectl create namespace vpc-control-plane-system --dry-run=client -o yaml | kubectl apply -f -

# Reuse an existing VPC identity key on rerun, otherwise generate it. Extract
# the Neutron shared secret only in a pipe and emit Kubernetes Secret objects;
# neither plaintext value is written to disk or echoed.
existing_identity=$(kubectl -n vpc-control-plane-system get secret vpc-instance-identity -o jsonpath='{.data.hmac-secret}' 2>/dev/null || true)
kubectl -n openstack get secret neutron-ovn-metadata-agent-default -o json |
  EXISTING_IDENTITY="$existing_identity" python3 -c '
import base64, configparser, io, json, os, secrets, sys
source=json.load(sys.stdin)["data"]["ovn_metadata_agent.ini"]
cfg=configparser.ConfigParser(); cfg.read_file(io.StringIO(base64.b64decode(source).decode()))
metadata=cfg["DEFAULT"].get("metadata_proxy_shared_secret", "")
if len(metadata) < 32: raise SystemExit("Neutron metadata shared secret is missing/short")
identity=base64.b64decode(os.environ["EXISTING_IDENTITY"]).decode() if os.environ.get("EXISTING_IDENTITY") else secrets.token_urlsafe(48)
def secret(namespace,name,data):
 return {"apiVersion":"v1","kind":"Secret","metadata":{"namespace":namespace,"name":name},"type":"Opaque","data":{k:base64.b64encode(v.encode()).decode() for k,v in data.items()}}
items=[secret("openstack","vpc-metadata-attestor-secrets",{"neutron-metadata-proxy-shared-secret":metadata,"vpc-instance-identity-hmac-secret":identity}),secret("vpc-control-plane-system","vpc-instance-identity",{"hmac-secret":identity})]
print(json.dumps({"apiVersion":"v1","kind":"List","items":items}))
' | kubectl apply -f -

python3 - "$VPC_REPO/config/production/metadata-attestor.yaml" "$ATTESTOR_IMAGE" <<'PY' | kubectl apply -f -
import sys, yaml
docs=list(yaml.safe_load_all(open(sys.argv[1])))
for doc in docs:
    if doc and doc.get("kind") == "DaemonSet":
        doc["spec"]["template"]["spec"]["containers"][0]["image"] = sys.argv[2]
yaml.safe_dump_all(docs, sys.stdout, sort_keys=False)
PY
kubectl -n openstack rollout status daemonset/vpc-metadata-attestor --timeout=10m

# Cut over only after both proxy replicas are Ready. --reuse-values preserves
# the current SOPS-derived release values; the same override is conditionally
# included by reconcile-full-stack.sh after this deployment exists.
helm upgrade neutron "$REPO_ROOT/helm/openstack-helm/neutron" -n openstack --reuse-values \
  -f "$REPO_ROOT/deploy/values/features/neutron-vpc-identity.yaml" --timeout 15m
kubectl -n openstack rollout status daemonset/neutron-ovn-metadata-agent-default --timeout=15m

kubectl -n vpc-control-plane-system rollout restart deployment/vpc-facade
kubectl -n vpc-control-plane-system rollout status deployment/vpc-facade --timeout=10m

configured=$(kubectl -n openstack get secret neutron-ovn-metadata-agent-default -o jsonpath='{.data.ovn_metadata_agent\.ini}' | base64 -d |
  python3 -c 'import configparser,sys; c=configparser.ConfigParser(); c.read_file(sys.stdin); print(c["DEFAULT"].get("nova_metadata_host", ""))')
test "$configured" = vpc-metadata-attestor.openstack.svc.cluster.local
"$REPO_ROOT/deploy/scripts/verify-vpc-instance-identity.sh"
echo "VPC instance identity path installed; validate ordinary metadata and /openstack/latest/vpc/identity from an opted-in test VM."
