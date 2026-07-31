#!/usr/bin/env bash
set -euo pipefail

namespace=${OCTAVIA_NAMESPACE:-openstack}
minimum_age=${OCTAVIA_PENDING_MIN_AGE_SECONDS:-900}
report_path=${1:-octavia-state-audit.json}

case "${minimum_age}" in
  ''|*[!0-9]*) echo "OCTAVIA_PENDING_MIN_AGE_SECONDS must be a positive integer." >&2; exit 2 ;;
esac

pod=$(
  kubectl -n "${namespace}" get pod \
    -l application=octavia,component=driver_agent -o json |
    python3 -c '
import json, sys
for pod in sorted(json.load(sys.stdin)["items"], key=lambda item: item["metadata"]["name"]):
    conditions = {c["type"]: c["status"] for c in pod.get("status", {}).get("conditions", [])}
    if pod.get("status", {}).get("phase") == "Running" and conditions.get("Ready") == "True":
        print(pod["metadata"]["name"])
        break
'
)
[[ -n "${pod}" ]] || { echo "No Ready octavia-driver-agent Pod found." >&2; exit 3; }

kubectl -n "${namespace}" exec -i "${pod}" -c octavia-driver-agent -- \
  /var/lib/openstack/bin/python - "${minimum_age}" >"${report_path}" <<'PY'
import datetime
import json
import re
import sys

from oslo_config import cfg
from oslo_log import log as logging
from ovn_octavia_provider.cmd import octavia_ovn_db_sync_util as sync_util
from ovn_octavia_provider.common import clients
from ovn_octavia_provider import driver

minimum_age = int(sys.argv[1])
sys.argv = [
    "octavia-state-audit",
    "--config-file", "/etc/octavia/octavia.conf",
    "--config-dir", "/etc/octavia/octavia.conf.d",
]
sync_util.setup_conf()
logging.setup(cfg.CONF, "octavia_state_audit")

now = datetime.datetime.now(datetime.timezone.utc)
uuid_pattern = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

def timestamp(value):
    if not value:
        return None
    parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed

def owners(row, key):
    return sorted(filter(None, row.external_ids.get(key, "").split(",")))

octavia = clients.get_octavia_client()
load_balancers = list(octavia.load_balancers())
lb_ids = {lb.id for lb in load_balancers}
ovn_lb_ids = {lb.id for lb in load_balancers if lb.provider == "ovn"}

provider = driver.OvnProviderDriver()
nb = provider._ovn_helper.ovn_nbdb_api
ovn_lbs = nb.db_list_rows("Load_Balancer").execute(check_error=True)
policies = nb.db_list_rows("Logical_Router_Policy").execute(check_error=True)
routes = nb.db_list_rows("Logical_Router_Static_Route").execute(check_error=True)

pending = []
for lb in load_balancers:
    status = str(lb.provisioning_status or "")
    updated = timestamp(lb.updated_at)
    age = int((now - updated).total_seconds()) if updated else None
    if status.startswith("PENDING_") and (age is None or age >= minimum_age):
        pending.append({
            "id": lb.id,
            "provider": lb.provider,
            "status": status,
            "ageSeconds": age,
            "updatedAt": str(lb.updated_at or ""),
        })

dangling_lb_rows = []
for row in ovn_lbs:
    # Octavia OVN rows are named with the Octavia LB UUID. Ignore Neutron's
    # non-Octavia Load_Balancer rows rather than treating every OVN LB as ours.
    if uuid_pattern.match(row.name or "") and row.name not in ovn_lb_ids:
        dangling_lb_rows.append({"uuid": str(row.uuid), "name": row.name})

orphaned_ownership = []
invalid_nexthops = []
for row, row_type, owner_key in (
    *((row, "policy", "octavia:cross_router_lb") for row in policies),
    *((row, "route", "octavia:cross_router_lb_route") for row in routes),
):
    row_owners = owners(row, owner_key)
    if not row_owners:
        continue
    missing = sorted({owner.split(":", 1)[0] for owner in row_owners} - lb_ids)
    if missing:
        orphaned_ownership.append({
            "type": row_type,
            "uuid": str(row.uuid),
            "missingLoadBalancers": missing,
            "owners": row_owners,
        })
    if row_type == "policy" and not list(getattr(row, "nexthops", []) or []):
        invalid_nexthops.append({
            "type": row_type, "uuid": str(row.uuid), "owners": row_owners,
        })
    if row_type == "route" and not str(getattr(row, "nexthop", "") or ""):
        invalid_nexthops.append({
            "type": row_type, "uuid": str(row.uuid), "owners": row_owners,
        })

report = {
    "generatedAt": now.isoformat(),
    "mode": "read-only",
    "thresholdSeconds": minimum_age,
    "longPending": pending,
    "orphanedCrossRouterOwnership": orphaned_ownership,
    "danglingOVNLoadBalancerRows": dangling_lb_rows,
    "invalidNexthops": invalid_nexthops,
}
report["summary"] = {
    "long_pending": len(pending),
    "orphaned_cross_router_ownership": len(orphaned_ownership),
    "dangling_ovn_load_balancer_rows": len(dangling_lb_rows),
    "invalid_nexthops": len(invalid_nexthops),
}
report["summary"]["total"] = sum(report["summary"].values())
print(json.dumps(report, indent=2, sort_keys=True))
PY

cat "${report_path}"

if [[ -n "${PUSHGATEWAY_URL:-}" ]]; then
  generated=$(python3 -c 'import datetime,json,sys; value=json.load(open(sys.argv[1]))["generatedAt"]; print(datetime.datetime.fromisoformat(value).timestamp())' "${report_path}")
  {
    echo '# HELP octavia_state_audit_issues Current Octavia and OVN state audit findings.'
    echo '# TYPE octavia_state_audit_issues gauge'
    for issue_type in long_pending orphaned_cross_router_ownership dangling_ovn_load_balancer_rows invalid_nexthops; do
      value=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["summary"][sys.argv[2]])' "${report_path}" "${issue_type}")
      printf 'octavia_state_audit_issues{type="%s"} %s\n' "${issue_type}" "${value}"
    done
    echo '# HELP octavia_state_audit_last_success_timestamp_seconds Last successful Octavia state audit.'
    echo '# TYPE octavia_state_audit_last_success_timestamp_seconds gauge'
    printf 'octavia_state_audit_last_success_timestamp_seconds %s\n' "${generated}"
  } | curl --fail --silent --show-error --data-binary @- \
    "${PUSHGATEWAY_URL%/}/metrics/job/octavia-state-audit"
fi

total=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["summary"]["total"])' "${report_path}")
if [[ "${total}" -ne 0 ]]; then
  echo "Octavia state audit found ${total} issue(s)." >&2
  exit 1
fi
