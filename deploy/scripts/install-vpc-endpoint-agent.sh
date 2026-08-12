#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
VPC_REPO=${VPC_CONTROL_PLANE_REPO:-$REPO_ROOT/../vpc-control-plane}
ENDPOINT_AGENT_IMAGE=${ENDPOINT_AGENT_IMAGE:?set ENDPOINT_AGENT_IMAGE to a digest-pinned image}
IMAGE_LOCK="$REPO_ROOT/deploy/locks/vpc-policy-images.yaml"
VPC_ENDPOINT_POLICY_FACADE_URL=${VPC_ENDPOINT_POLICY_FACADE_URL:?set VPC_ENDPOINT_POLICY_FACADE_URL to the HTTPS VPC facade URL reachable from tenant subnets}
[[ "$ENDPOINT_AGENT_IMAGE" == *@sha256:* ]] || { echo "endpoint agent image must be digest-pinned" >&2; exit 1; }
[[ "$VPC_ENDPOINT_POLICY_FACADE_URL" == https://* ]] || { echo "endpoint policy facade URL must use HTTPS" >&2; exit 1; }
[[ ${APPROVE_VPC_ENDPOINT_DATAPLANE:-no} == yes ]] || {
  echo "Review service CIDRs and privileged compute-node placement, then set APPROVE_VPC_ENDPOINT_DATAPLANE=yes." >&2
  exit 1
}
test -f "$VPC_REPO/config/production/endpoint-agent.yaml"
git -C "$VPC_REPO" diff --quiet && git -C "$VPC_REPO" diff --cached --quiet || { echo "refusing endpoint-agent cutover from dirty VPC source" >&2; exit 1; }
locked_revision=$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["spec"]["sourceRevision"])' "$IMAGE_LOCK")
locked_image=$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["spec"].get("endpointAgentImage", ""))' "$IMAGE_LOCK")
git -C "$VPC_REPO" merge-base --is-ancestor "$locked_revision" HEAD &&
  git -C "$VPC_REPO" diff --quiet "$locked_revision" HEAD -- . ':(exclude)config/production/kustomization.yaml' &&
  [[ "$ENDPOINT_AGENT_IMAGE" == "$locked_image" ]] || { echo "endpoint agent image/source does not match the production VPC image lock" >&2; exit 1; }
{
  kubectl -n openstack get secret vpc-endpoint-policy-hmac -o jsonpath='{.data.hmac-secret}' 2>/dev/null || true
  printf '\n'
  kubectl -n vpc-control-plane-system get secret vpc-endpoint-policy-hmac -o jsonpath='{.data.hmac-secret}' 2>/dev/null || true
  printf '\n'
} | python3 -c '
import base64, secrets, sys
values=[value.strip() for value in sys.stdin.read().splitlines() if value.strip()]
if len(set(values)) > 1: raise SystemExit("existing endpoint-policy HMAC secrets differ; refusing implicit rotation")
if values:
 try: decoded=base64.b64decode(values[0], validate=True)
 except Exception as exc: raise SystemExit("existing endpoint-policy HMAC secret is not valid base64") from exc
 if len(decoded) < 32: raise SystemExit("existing endpoint-policy HMAC secret is shorter than 32 bytes")
 key=values[0]
else: key=base64.b64encode(secrets.token_bytes(48)).decode()
print(key,end="")
' | python3 -c 'import json,sys; key=sys.stdin.read().strip(); items=[{"apiVersion":"v1","kind":"Secret","metadata":{"name":"vpc-endpoint-policy-hmac","namespace":ns},"type":"Opaque","data":{"hmac-secret":key}} for ns in ("openstack","vpc-control-plane-system")]; print(json.dumps({"apiVersion":"v1","kind":"List","items":items}))' | kubectl apply -f -

python3 - "$VPC_REPO/config/production/endpoint-agent.yaml" "$ENDPOINT_AGENT_IMAGE" "${VPC_ENDPOINT_SERVICE_CIDRS:-192.168.21.0/24}" "$VPC_ENDPOINT_POLICY_FACADE_URL" <<'PY' | kubectl apply -f -
import sys,yaml
path,image,cidrs,facade=sys.argv[1:]
for doc in yaml.safe_load_all(open(path)):
    if not doc: continue
    if doc.get("kind") == "DaemonSet":
        container=doc["spec"]["template"]["spec"]["containers"][0]
        container["image"]=image
        container["args"]=[f"--allowed-service-cidrs={cidrs}",f"--policy-facade-url={facade}"]
    print(yaml.safe_dump(doc,sort_keys=False),end="---\n")
PY
policy_checksum=$(kubectl -n vpc-control-plane-system get secret vpc-endpoint-policy-hmac -o jsonpath='{.data.hmac-secret}' | sha256sum | awk '{print $1}')
kubectl -n vpc-control-plane-system patch deployment vpc-facade --type=merge -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"vpc.dcn.ssu.ac.kr/endpoint-policy-secret-checksum\":\"${policy_checksum}\"}}}}}" >/dev/null
kubectl -n vpc-control-plane-system rollout status deployment/vpc-facade --timeout=5m
kubectl -n openstack rollout status daemonset/vpc-endpoint-agent --timeout=15m
VPC_ENDPOINT_POLICY_FACADE_URL="$VPC_ENDPOINT_POLICY_FACADE_URL" "$REPO_ROOT/deploy/scripts/verify-vpc-endpoint-agent.sh"
echo "VPC endpoint agent installed; create an interface endpoint with validationProbeRef before declaring it available."
