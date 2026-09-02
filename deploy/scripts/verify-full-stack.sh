#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
NAMESPACE=${NAMESPACE:-openstack}
PUBLIC_GATEWAY_IP=${PUBLIC_GATEWAY_IP:-10.67.10.6}

public_status() {
  local path=$1 code attempt
  for attempt in $(seq 1 30); do
    code=$(curl -ksS --connect-timeout 2 --max-time 10 \
      --resolve "cloud.dcn.ssu.ac.kr:443:${PUBLIC_GATEWAY_IP}" \
      -o /dev/null -w '%{http_code}' "https://cloud.dcn.ssu.ac.kr${path}" 2>/dev/null || true)
    if [[ "$code" != "000" && -n "$code" ]]; then
      printf '%s\n' "$code"
      return 0
    fi
    sleep 1
  done
  printf '000\n'
}

"$REPO_ROOT/deploy/scripts/verify-image-rebuild-closure.py"

python3 - "$REPO_ROOT/release-lock.yaml" <<'PYLOCK' | while read -r release expected; do
import sys,yaml
x=yaml.safe_load(open(sys.argv[1]))['spec']['releases']
for r in x: print(r['name'],r['chartVersion'])
PYLOCK
  actual=$(helm list -n "$NAMESPACE" -f "^${release}$" -o json     | python3 -c 'import json,sys; x=json.load(sys.stdin); print(x[0]["chart"].rsplit("-",1)[-1] if x else "missing")')
  [[ "$actual" == "$expected" ]] || {
    echo "$release version mismatch: expected $expected, got $actual" >&2; exit 1;
  }
done

neutron_desired=$(kubectl get deployment -n "$NAMESPACE" neutron-server -o jsonpath='{.spec.replicas}')
neutron_ready=$(kubectl get deployment -n "$NAMESPACE" neutron-server -o jsonpath='{.status.readyReplicas}')
[[ "$neutron_desired" =~ ^[0-9]+$ && "$neutron_desired" -ge 2 ]] || {
  echo "Neutron API desired replicas must be at least two, got ${neutron_desired:-unset}" >&2; exit 1;
}
[[ "$neutron_ready" == "$neutron_desired" ]] || {
  echo "Neutron API ready replicas ${neutron_ready:-0} do not match desired replicas $neutron_desired" >&2; exit 1;
}
neutron_zones=$(kubectl get pods -n "$NAMESPACE" -l application=neutron,component=server \
  -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | \
  xargs -r -n1 kubectl get node -o jsonpath='{.metadata.labels.topology\.kubernetes\.io/zone}{"\n"}' | sort -u | wc -l)
[[ "$neutron_zones" == "$neutron_desired" ]] || {
  echo "Neutron API spans $neutron_zones rack zones, expected $neutron_desired" >&2; exit 1;
}

for release in $(helm list -n "$NAMESPACE" -q); do
  status=$(helm status -n "$NAMESPACE" "$release" -o json     | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["status"])')
  [[ "$status" == deployed ]] || { echo "$release status=$status" >&2; exit 1; }
done

kubectl get pods -n "$NAMESPACE" -o json | ALLOWED_UNREADY_PODS="${ALLOWED_UNREADY_PODS:-}" python3 /dev/fd/3 3<<'PODCHECK'
import json
import os
import sys

pods = json.load(sys.stdin)["items"]
allowed = {name for name in os.environ.get("ALLOWED_UNREADY_PODS", "").split(",") if name}
bad = []
historical = []
seen_allowed = set()
for pod in pods:
    name = pod["metadata"]["name"]
    phase = pod.get("status", {}).get("phase", "Unknown")
    owners = pod["metadata"].get("ownerReferences", [])
    owner_kind = owners[0].get("kind") if owners else None
    if phase == "Succeeded":
        continue
    if phase == "Failed" and owner_kind in {None, "Job"}:
        historical.append(name)
        continue
    statuses = pod.get("status", {}).get("containerStatuses", [])
    if phase != "Running" or any(not status.get("ready", False) for status in statuses):
        if name in allowed:
            seen_allowed.add(name)
            print(f"warning: accepting explicitly allowed unready Pod: {name}", file=sys.stderr)
            continue
        bad.append(f"{name}: phase={phase}, owner={owner_kind or 'none'}")

missing = allowed - seen_allowed
if missing:
    print("allowed unready Pods were not observed unready: " + ", ".join(sorted(missing)), file=sys.stderr)
    raise SystemExit(1)

for name in historical:
    print(f"warning: ignoring retained terminal test/job Pod: {name}", file=sys.stderr)
if bad:
    print("\n".join(bad), file=sys.stderr)
    raise SystemExit(1)
PODCHECK

for workload in octavia-api octavia-driver-agent octavia-housekeeping; do
  [[ "$(kubectl get deployment -n "$NAMESPACE" "$workload" -o jsonpath='{.status.readyReplicas}')" -ge 2 ]] || {
    echo "$workload does not have at least two ready replicas" >&2; exit 1;
  }
  [[ "$(kubectl get pods -n "$NAMESPACE" -l "application=octavia" -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u | wc -l)" -ge 2 ]] || {
    echo "Octavia replicas are not spread across two nodes" >&2; exit 1;
  }
done

[[ "$(public_status /load-balancer/v2/lbaas/providers)" == "401" ]] || {
  echo "public Octavia route did not enforce Keystone authentication" >&2; exit 1;
}

for dashboard in skyline horizon; do
  component=skyline
  [[ "$dashboard" == horizon ]] && component=server
  expected_replicas=2
  [[ "$dashboard" == horizon ]] && expected_replicas=3
  [[ "$(kubectl get deployment -n "$NAMESPACE" "$dashboard" -o jsonpath='{.status.readyReplicas}')" == "$expected_replicas" ]] || {
    echo "$dashboard does not have $expected_replicas ready replicas" >&2; exit 1;
  }
  [[ "$(kubectl get pods -n "$NAMESPACE" -l "application=$dashboard,component=$component" -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u | wc -l)" -ge 2 ]] || {
    echo "$dashboard replicas are not spread across two nodes" >&2; exit 1;
  }
done

# Horizon stores compressed bundles on a pod-local emptyDir. Its compressor
# metadata must therefore also be pod-local; sharing that cache previously let
# one replica advertise a JavaScript hash which existed only on another pod.
# Offline mode is safe because each Pod runs collectstatic + compress with the
# final /horizon STATIC_URL before Apache starts. It prevents expensive
# request-time template compression in every WSGI worker.
mapfile -t horizon_pods < <(kubectl get pods -n "$NAMESPACE" \
  -l application=horizon,component=server,release_group=horizon \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort)
[[ "${#horizon_pods[@]}" -eq 3 ]] || {
  echo "expected three Horizon server pods" >&2; exit 1;
}
[[ "$(kubectl get service -n "$NAMESPACE" horizon-int -o jsonpath='{.spec.sessionAffinity}')" == ClientIP ]] || {
  echo "Horizon service does not use ClientIP affinity" >&2; exit 1;
}
horizon_zones=$(printf '%s\n' "${horizon_pods[@]}" | xargs -r -n1 kubectl get pod -n "$NAMESPACE" \
  -o jsonpath='{.spec.nodeName}{"\n"}' | xargs -r -n1 kubectl get node \
  -o jsonpath='{.metadata.labels.topology\.kubernetes\.io/zone}{"\n"}' | sort -u | wc -l)
schedulable_control_plane_zones=$(kubectl get nodes -l openstack-control-plane=enabled -o json | python3 -c '
import json, sys
nodes = json.load(sys.stdin)["items"]
zones = {
    node["metadata"].get("labels", {}).get("topology.kubernetes.io/zone")
    for node in nodes
    if not node.get("spec", {}).get("unschedulable", False)
    and any(condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in node.get("status", {}).get("conditions", []))
}
print(len(zones - {None}))')
horizon_expected_zones=$(( schedulable_control_plane_zones < 3 ? schedulable_control_plane_zones : 3 ))
[[ "$horizon_expected_zones" -ge 2 && "$horizon_zones" == "$horizon_expected_zones" ]] || {
  echo "Horizon replicas span $horizon_zones rack zones, expected $horizon_expected_zones schedulable zones" >&2; exit 1;
}
horizon_bundle=''
for pod in "${horizon_pods[@]}"; do
  settings=$(kubectl exec -n "$NAMESPACE" "$pod" -- /tmp/manage.py shell -c \
    'from django.conf import settings; print(settings.COMPRESS_OFFLINE, settings.COMPRESS_CACHE_BACKEND, settings.CACHES[settings.COMPRESS_CACHE_BACKEND]["BACKEND"], settings.STATIC_URL, settings.DATABASES["default"]["CONN_MAX_AGE"], settings.DATABASES["default"]["CONN_HEALTH_CHECKS"])')
  [[ "$settings" == *"True compressor django.core.cache.backends.locmem.LocMemCache /horizon/static/ 60 True"* ]] || {
    echo "$pod has unsafe Horizon compressor settings: $settings" >&2; exit 1;
  }
  apache=$(kubectl exec -n "$NAMESPACE" "$pod" -- grep WSGIDaemonProcess /etc/apache2/sites-enabled/000-default.conf)
  [[ "$apache" == *"processes=4 threads=2 maximum-requests=2000"* ]] || {
    echo "$pod has unexpected Horizon WSGI concurrency: $apache" >&2; exit 1;
  }
  bundle=$(kubectl exec -n "$NAMESPACE" "$pod" -- sh -c \
    "find /var/www/html -name 'angular_template_cache_preloads*.js' -printf '%f %s\\n' | sort")
  [[ "$(printf '%s\n' "$bundle" | sed '/^$/d' | wc -l)" -eq 1 ]] || {
    echo "$pod has an unexpected Angular preload bundle set: $bundle" >&2; exit 1;
  }
  if [[ -n "$horizon_bundle" && "$bundle" != "$horizon_bundle" ]]; then
    echo "Horizon replicas generated different Angular preload bundles" >&2
    printf '%s: %s\n' "$pod" "$bundle" >&2
    exit 1
  fi
  horizon_bundle=$bundle
done

# Catch regressions where login rendering silently performs runtime asset
# compression again. Use the median to tolerate one connection/setup outlier.
mapfile -t login_samples < <(for _ in 1 2 3 4 5; do
  curl -ksS --connect-timeout 2 --max-time 10 \
    --resolve "cloud.dcn.ssu.ac.kr:443:${PUBLIC_GATEWAY_IP}" \
    -o /dev/null -w '%{time_starttransfer}\n' \
    https://cloud.dcn.ssu.ac.kr/horizon/auth/login/
done | sort -n)
[[ "${#login_samples[@]}" -eq 5 ]] || {
  echo "Horizon login TTFB sampling did not return five results" >&2; exit 1;
}
python3 - "${login_samples[2]}" <<'PY'
import sys
median = float(sys.argv[1])
if median >= 1.0:
    raise SystemExit(f"Horizon login median TTFB too high: {median:.3f}s (limit 1.000s)")
print(f"Horizon login median TTFB: {median:.3f}s")
PY

kubectl get pdb -n "$NAMESPACE" skyline >/dev/null
[[ "$(kubectl get deployment -n "$NAMESPACE" barbican-api -o jsonpath='{.status.readyReplicas}')" == "2" ]]
[[ "$(kubectl get pdb -n "$NAMESPACE" barbican-api -o jsonpath='{.spec.minAvailable}')" == "1" ]]
[[ "$(public_status /key-manager/v1/secrets)" == "401" ]] || {
  echo "public Barbican route did not enforce Keystone authentication" >&2; exit 1;
}
kubectl get httproute -n "$NAMESPACE" openstack-public-services \
  -o jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}' | grep -qx True

"$REPO_ROOT/deploy/scripts/verify.sh"
