#!/usr/bin/env bash
set -euo pipefail

# Consolidate the historical RegionOne and RegionOne-VM catalogs into the
# single user-facing production region. Keystone region objects do not have an
# enabled flag, so retirement is represented by disabling every endpoint in
# the old regions. The region objects remain for audit and rollback.
export TARGET_REGION=${TARGET_REGION:-seoul-ssu-1}
export LEGACY_REGIONS=${LEGACY_REGIONS:-"RegionOne RegionOne-VM"}

# Phase 50 normally runs this script on an Ansible controller, where the
# Keystone credentials deliberately exist only in Kubernetes. Re-enter the
# same script in a short-lived client Pod with the admin Secret injected.
if [[ -z "${OS_AUTH_URL:-}" ]]; then
  namespace=${NAMESPACE:-openstack}
  pod=keystone-region-reconcile
  cleanup_region_pod() {
    kubectl -n "$namespace" delete pod "$pod" \
      --ignore-not-found --wait=false >/dev/null 2>&1 || true
  }
  trap cleanup_region_pod EXIT
  kubectl -n "$namespace" delete pod "$pod" --ignore-not-found --wait=true
  kubectl -n "$namespace" run "$pod" \
    --image=quay.io/airshipit/openstack-client:2026.1-ubuntu_noble \
    --restart=Never --command \
    --overrides="{\"spec\":{\"containers\":[{\"name\":\"$pod\",\"image\":\"quay.io/airshipit/openstack-client:2026.1-ubuntu_noble\",\"command\":[\"sleep\",\"600\"],\"envFrom\":[{\"secretRef\":{\"name\":\"keystone-keystone-admin\"}}]}]}}" \
    -- sleep 600
  kubectl -n "$namespace" wait --for=condition=Ready "pod/$pod" --timeout=5m
  kubectl -n "$namespace" exec -i "$pod" -- \
    env TARGET_REGION="$TARGET_REGION" LEGACY_REGIONS="$LEGACY_REGIONS" \
    bash -s <"$0"
  exit
fi

# Use one password-authenticated keystoneauth Session and address Keystone by
# OS_AUTH_URL directly. Calling the OSC executable once per endpoint both
# re-authenticates dozens of times and starts consulting the catalog midway
# through its own migration, which can strand the operation on a retired
# endpoint.
python3 <<'PY'
import os

from keystoneauth1 import identity, session

auth_url = os.environ["OS_AUTH_URL"].rstrip("/")
target = os.environ["TARGET_REGION"]
legacy = os.environ["LEGACY_REGIONS"].split()
auth = identity.v3.Password(
    auth_url=auth_url,
    username=os.environ["OS_USERNAME"],
    password=os.environ["OS_PASSWORD"],
    project_name=os.environ["OS_PROJECT_NAME"],
    user_domain_name=os.environ["OS_USER_DOMAIN_NAME"],
    project_domain_name=os.environ["OS_PROJECT_DOMAIN_NAME"],
)
client = session.Session(auth=auth)


def request(method, path, **kwargs):
    response = client.request(
        f"{auth_url}/{path.lstrip('/')}",
        method=method,
        endpoint_override=auth_url,
        **kwargs,
    )
    response.raise_for_status()
    return response


region_response = client.get(
    f"{auth_url}/regions/{target}", endpoint_override=auth_url
)
if region_response.status_code == 404:
    request(
        "PUT",
        f"regions/{target}",
        json={"region": {"description": "Seoul SSU production region"}},
    )
else:
    region_response.raise_for_status()

endpoints = request("GET", "endpoints").json()["endpoints"]
legacy_endpoints = [item for item in endpoints if item["region_id"] in legacy]
target_endpoints = [item for item in endpoints if item["region_id"] == target]

# Prefer RegionOne for every interface. In particular, its internal URLs are
# cluster-local and remain correct for OpenStack services. VM workloads use
# the public interface in the unified region; one region cannot safely carry
# two different internal endpoints for the same service.
selected = {}
for item in legacy_endpoints:
    key = (item["service_id"], item["interface"])
    score = 2 if item["region_id"] == "RegionOne" else 1
    if key not in selected or score > selected[key][0]:
        selected[key] = (score, item)

for key, (_, source) in sorted(selected.items()):
    matches = [
        item for item in target_endpoints
        if (item["service_id"], item["interface"]) == key
    ]
    if not matches:
        created = request(
            "POST",
            "endpoints",
            json={"endpoint": {
                "service_id": source["service_id"],
                "interface": source["interface"],
                "region_id": target,
                "url": source["url"],
                "enabled": True,
            }},
        ).json()["endpoint"]
        target_endpoints.append(created)
        matches = [created]
    request(
        "PATCH",
        f"endpoints/{matches[0]['id']}",
        json={"endpoint": {"url": source["url"], "enabled": True}},
    )
    for duplicate in matches[1:]:
        request(
            "PATCH",
            f"endpoints/{duplicate['id']}",
            json={"endpoint": {"enabled": False}},
        )

for endpoint in legacy_endpoints:
    if endpoint["enabled"]:
        request(
            "PATCH",
            f"endpoints/{endpoint['id']}",
            json={"endpoint": {"enabled": False}},
        )

final = request("GET", "endpoints").json()["endpoints"]
enabled_target = [x for x in final if x["region_id"] == target and x["enabled"]]
if not enabled_target:
    raise SystemExit(f"{target} has no enabled endpoints")
for region in legacy:
    if any(x["region_id"] == region and x["enabled"] for x in final):
        raise SystemExit(f"legacy region still has enabled endpoints: {region}")

print(
    f"Keystone catalog consolidated into {target}: "
    f"{len(enabled_target)} enabled endpoints; legacy endpoints disabled."
)
PY
