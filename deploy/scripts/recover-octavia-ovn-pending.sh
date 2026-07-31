#!/usr/bin/env bash
set -euo pipefail

namespace=${OCTAVIA_NAMESPACE:-openstack}
minimum_age=${OCTAVIA_PENDING_MIN_AGE_SECONDS:-900}
poll_attempts=${OCTAVIA_PENDING_RECOVERY_ATTEMPTS:-60}
lb_ref=${1:-}

case "${minimum_age}:${poll_attempts}" in
  *[!0-9:]*|:*|*:) echo "Age and attempt settings must be positive integers." >&2; exit 2 ;;
esac

field() {
  local key=$1
  python3 -c '
import json, sys
wanted = sys.argv[1].lower().replace(" ", "_")
data = json.load(sys.stdin)
for key, value in data.items():
    if key.lower().replace(" ", "_") == wanted:
        print("" if value is None else value)
        break
' "${key}"
}

show_lb() {
  openstack loadbalancer show "$1" -f json \
    -c id -c provider -c provisioning_status -c updated_at
}

age_seconds() {
  python3 -c '
from datetime import datetime, timezone
import sys
value = sys.argv[1]
if not value:
    raise SystemExit("load balancer has no updated_at timestamp")
stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
if stamp.tzinfo is None:
    stamp = stamp.replace(tzinfo=timezone.utc)
print(max(0, int((datetime.now(timezone.utc) - stamp).total_seconds())))
' "$1"
}

inspect_lb() {
  local ref=$1 details id provider status updated age
  details=$(show_lb "${ref}")
  id=$(field id <<<"${details}")
  provider=$(field provider <<<"${details}")
  status=$(field provisioning_status <<<"${details}")
  updated=$(field updated_at <<<"${details}")
  age=$(age_seconds "${updated}")
  printf 'id=%s provider=%s provisioning_status=%s age_seconds=%s updated_at=%s\n' \
    "${id}" "${provider}" "${status}" "${age}" "${updated}"
  [[ "${provider}" == ovn && "${status}" == PENDING_* && "${age}" -ge "${minimum_age}" ]]
}

if [[ -z "${lb_ref}" ]]; then
  found=0
  while IFS= read -r id; do
    [[ -n "${id}" ]] || continue
    if inspect_lb "${id}"; then
      found=1
    fi
  done < <(
    openstack loadbalancer list -f json -c id -c provisioning_status |
      python3 -c '
import json, sys
for row in json.load(sys.stdin):
    normalized = {k.lower().replace(" ", "_"): v for k, v in row.items()}
    if str(normalized.get("provisioning_status", "")).startswith("PENDING_"):
        print(normalized["id"])
'
  )
  if [[ "${found}" -eq 1 ]]; then
    echo "One or more OVN load balancers require operator review." >&2
    exit 1
  fi
  echo "No OVN load balancer has exceeded the pending threshold."
  exit 0
fi

if ! inspect_lb "${lb_ref}"; then
  echo "Refusing recovery: target is not an OVN PENDING_* load balancer older than ${minimum_age}s." >&2
  exit 3
fi

if [[ "${OCTAVIA_OVN_PENDING_RECOVERY:-}" != YES ]]; then
  echo "Dry run only. Set OCTAVIA_OVN_PENDING_RECOVERY=YES to run targeted provider synchronization."
  exit 0
fi

read -r generation observed replicas ready updated available < <(
  kubectl -n "${namespace}" get deployment octavia-driver-agent -o json |
    python3 -c '
import json, sys
d = json.load(sys.stdin)
print(d["metadata"]["generation"], d.get("status", {}).get("observedGeneration", 0),
      d["spec"].get("replicas", 0), d.get("status", {}).get("readyReplicas", 0),
      d.get("status", {}).get("updatedReplicas", 0), d.get("status", {}).get("availableReplicas", 0))
'
)
if [[ "${generation}" != "${observed}" || "${replicas}" != "${ready}" || \
      "${replicas}" != "${updated}" || "${replicas}" != "${available}" ]]; then
  echo "Refusing recovery while octavia-driver-agent rollout is not stable." >&2
  exit 4
fi

if command -v helm >/dev/null 2>&1; then
  helm_status=$(helm -n "${namespace}" status octavia -o json |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["status"])')
  if [[ "${helm_status}" != deployed ]]; then
    echo "Refusing recovery while Octavia Helm status is ${helm_status}." >&2
    exit 5
  fi
fi

pod=$(
  kubectl -n "${namespace}" get pod \
    -l application=octavia,component=driver_agent -o json |
    python3 -c '
import json, sys
for pod in sorted(json.load(sys.stdin)["items"], key=lambda p: p["metadata"]["name"]):
    conditions = {c["type"]: c["status"] for c in pod.get("status", {}).get("conditions", [])}
    if pod.get("status", {}).get("phase") == "Running" and conditions.get("Ready") == "True":
        print(pod["metadata"]["name"])
        break
'
)
[[ -n "${pod}" ]] || { echo "No Ready octavia-driver-agent Pod found." >&2; exit 6; }

lb_id=$(field id <<<"$(show_lb "${lb_ref}")")
echo "Synchronizing OVN load balancer ${lb_id} through ${pod}."
kubectl -n "${namespace}" exec -i "${pod}" -c octavia-driver-agent -- \
  /var/lib/openstack/bin/python - "${lb_id}" <<'PY'
import sys

from oslo_config import cfg
from oslo_log import log as logging
from ovn_octavia_provider.cmd import octavia_ovn_db_sync_util as sync_util
from ovn_octavia_provider import driver

lb_id = sys.argv[1]
sys.argv = [
    'octavia-ovn-db-sync-util',
    '--config-file', '/etc/octavia/octavia.conf',
    '--config-dir', '/etc/octavia/octavia.conf.d',
]
sync_util.setup_conf()
logging.setup(cfg.CONF, 'octavia_ovn_pending_recovery')
driver.OvnProviderDriver().do_sync(provider='ovn', id=lb_id)
PY

for attempt in $(seq 1 "${poll_attempts}"); do
  details=$(show_lb "${lb_id}")
  status=$(field provisioning_status <<<"${details}")
  echo "attempt=${attempt} provisioning_status=${status}"
  if [[ "${status}" == ACTIVE ]]; then
    openstack loadbalancer status show "${lb_id}"
    echo "OVN load balancer recovery completed without direct database changes."
    exit 0
  fi
  [[ "${status}" == ERROR ]] && exit 7
  sleep 5
done

echo "Recovery did not reach ACTIVE within the polling window." >&2
exit 8
