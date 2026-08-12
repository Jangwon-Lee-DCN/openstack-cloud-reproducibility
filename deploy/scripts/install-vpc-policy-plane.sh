#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
VPC_REPO=${VPC_CONTROL_PLANE_REPO:-$REPO_ROOT/../vpc-control-plane}
NAMESPACE=vpc-control-plane-system
IMAGE_LOCK="$REPO_ROOT/deploy/locks/vpc-policy-images.yaml"

test -f "$VPC_REPO/config/production/kustomization.yaml"
test -f "$IMAGE_LOCK"
git -C "$VPC_REPO" diff --quiet && git -C "$VPC_REPO" diff --cached --quiet || {
  echo "refusing CRD/controller rollout from dirty VPC source; commit and lock the exact revision first" >&2
  exit 1
}
locked_revision=$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["spec"]["sourceRevision"])' "$IMAGE_LOCK")
git -C "$VPC_REPO" merge-base --is-ancestor "$locked_revision" HEAD &&
  git -C "$VPC_REPO" diff --quiet "$locked_revision" HEAD -- . ':(exclude)config/production/kustomization.yaml' || {
  echo "VPC source after the locked build differs outside the promoted image-pin file" >&2
  exit 1
}
# The facade validates caller tokens and creates project-scoped Application
# Credentials through Keystone. Materialize its exact-name clouds.yaml Secret
# from the already encrypted/reconciled Keystone administrator Secret; no
# plaintext credential is written to disk or printed.
kubectl -n openstack get secret keystone-keystone-admin -o json |
  python3 -c 'import base64,json,sys,yaml; s=json.load(sys.stdin)["data"]; g=lambda k:base64.b64decode(s[k]).decode(); cloud={"clouds":{"openstack":{"auth":{"auth_url":g("OS_AUTH_URL"),"username":g("OS_USERNAME"),"password":g("OS_PASSWORD"),"project_name":g("OS_PROJECT_NAME"),"user_domain_name":g("OS_USER_DOMAIN_NAME"),"project_domain_name":g("OS_PROJECT_DOMAIN_NAME")},"region_name":g("OS_REGION_NAME"),"interface":g("OS_INTERFACE"),"identity_api_version":3,"verify":False}}}; raw=yaml.safe_dump(cloud,sort_keys=False).encode(); out={"apiVersion":"v1","kind":"Secret","metadata":{"name":"vpc-facade-service-credentials","namespace":"openstack"},"type":"Opaque","data":{"clouds.yaml":base64.b64encode(raw).decode()}}; print(json.dumps(out))' |
  kubectl apply -f -
# Neutron service credentials are used solely for the privileged
# binding:host_id transition of interface endpoint ports. Tenant credentials
# continue to own port/IP/security-group lifecycle.
kubectl -n openstack get secret neutron-keystone-user -o json |
  python3 -c 'import base64,json,sys,yaml; s=json.load(sys.stdin)["data"]; g=lambda k:base64.b64decode(s[k]).decode(); cloud={"clouds":{"openstack":{"auth":{"auth_url":g("OS_AUTH_URL"),"username":g("OS_USERNAME"),"password":g("OS_PASSWORD"),"project_name":g("OS_PROJECT_NAME"),"user_domain_name":g("OS_USER_DOMAIN_NAME"),"project_domain_name":g("OS_PROJECT_DOMAIN_NAME")},"region_name":g("OS_REGION_NAME"),"interface":g("OS_INTERFACE"),"identity_api_version":3,"verify":False}}}; raw=yaml.safe_dump(cloud,sort_keys=False).encode(); out={"apiVersion":"v1","kind":"Secret","metadata":{"name":"vpc-endpoint-binding-credentials","namespace":"openstack"},"type":"Opaque","data":{"clouds.yaml":base64.b64encode(raw).decode()}}; print(json.dumps(out))' |
  kubectl apply -f -
render_production() {
  kubectl kustomize "$VPC_REPO/config/production" |
    "$REPO_ROOT/deploy/scripts/render-vpc-policy-plane.py" "$IMAGE_LOCK"
}
# Validate the complete locked stream before applying any VPC control-plane
# object. This catches a missing CRD or controller/facade image mismatch before
# the rollout begins.
rendered=$(mktemp)
trap 'rm -f "$rendered"' EXIT
render_production > "$rendered"
python3 - "$rendered" "$IMAGE_LOCK" <<'PY'
import sys, yaml
documents=[item for item in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")) if item]
lock=yaml.safe_load(open(sys.argv[2], encoding="utf-8"))["spec"]
crds={item.get("metadata",{}).get("name") for item in documents if item.get("kind")=="CustomResourceDefinition"}
required={
  "connectivityprobes.vpc.dcn.ssu.ac.kr", "vpcendpoints.vpc.dcn.ssu.ac.kr",
  "vpcendpointservices.vpc.dcn.ssu.ac.kr", "flowlogconfigs.vpc.dcn.ssu.ac.kr",
  "ipampools.vpc.dcn.ssu.ac.kr", "ipamallocations.vpc.dcn.ssu.ac.kr",
  "routeservers.vpc.dcn.ssu.ac.kr", "trafficmirrorsessions.vpc.dcn.ssu.ac.kr",
}
if not required <= crds: raise SystemExit(f"production render lacks CRDs: {sorted(required-crds)}")
images={item["metadata"]["name"]:item["spec"]["template"]["spec"]["containers"][0]["image"] for item in documents if item.get("kind")=="Deployment" and item["metadata"]["name"] in ("vpc-control-plane-controller-manager","vpc-facade")}
expected={"vpc-control-plane-controller-manager":lock["controllerImage"],"vpc-facade":lock["facadeImage"]}
if images != expected: raise SystemExit(f"rendered locked images differ: {images!r} != {expected!r}")
PY
kubectl apply -f "$rendered"

# Derive a namespace-local pull secret from Harbor's reproducibly installed
# administrator Secret without writing or printing the credential.
kubectl -n harbor get secret harbor-admin-password -o json |
  python3 -c 'import base64,json,sys; s=json.load(sys.stdin); p=base64.b64decode(s["data"]["HARBOR_ADMIN_PASSWORD"]).decode(); cfg={"auths":{"registry.dcn.ssu.ac.kr":{"username":"admin","password":p,"auth":base64.b64encode(("admin:"+p).encode()).decode()}}}; out={"apiVersion":"v1","kind":"Secret","metadata":{"name":"vpc-registry-pull","namespace":"vpc-control-plane-system"},"type":"kubernetes.io/dockerconfigjson","data":{".dockerconfigjson":base64.b64encode(json.dumps(cfg,separators=(",", ":")).encode()).decode()}}; print(json.dumps(out))' |
  kubectl apply -f -

# The first apply creates the namespace; repeat so Deployments can consume the
# pull Secret immediately and so this remains safe after a clean rebuild.
kubectl apply -f "$rendered"
kubectl apply -k "$VPC_REPO/config/gateway"
if kubectl get crd servicemonitors.monitoring.coreos.com >/dev/null 2>&1; then
  kubectl apply -k "$VPC_REPO/config/monitoring"
fi

credential_checksum=$(kubectl -n openstack get secret vpc-facade-service-credentials \
  -o jsonpath='{.data.clouds\.yaml}' | sha256sum | awk '{print $1}')
kubectl -n "$NAMESPACE" patch deployment vpc-facade --type=merge \
  -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"dcn.ssu.ac.kr/service-credential-checksum\":\"${credential_checksum}\"}}}}}" >/dev/null

for deployment in vpc-control-plane-controller-manager vpc-facade opa-pilot; do
  kubectl -n "$NAMESPACE" rollout status "deployment/$deployment" --timeout=15m
done
"$REPO_ROOT/deploy/scripts/verify-vpc-policy-plane.sh"
