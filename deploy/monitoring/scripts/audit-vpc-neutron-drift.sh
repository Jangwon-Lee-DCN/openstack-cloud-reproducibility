#!/usr/bin/env bash
set -euo pipefail

# Run the exact production auditor once. This deliberately does not maintain a
# second, reduced implementation of the drift contract.
project_namespace=${1:?usage: audit-vpc-neutron-drift.sh PROJECT_NAMESPACE [REPORT.json]}
report_path=${2:-vpc-neutron-drift-${project_namespace}.json}
cronjob=vpc-neutron-drift-auditor
job="${cronjob}-manual-$(date -u +%Y%m%d%H%M%S)"

kubectl -n "$project_namespace" get cronjob "$cronjob" >/dev/null || {
  echo "Install the per-project auditor first: deploy/monitoring/scripts/install-drift-auditor.sh $project_namespace" >&2
  exit 1
}
kubectl -n "$project_namespace" get secret openstack-credentials >/dev/null || {
  echo "$project_namespace/openstack-credentials is required" >&2
  exit 1
}

kubectl -n "$project_namespace" create job --from="cronjob/$cronjob" "$job" >/dev/null
echo "created read-only audit job $project_namespace/$job" >&2
if ! kubectl -n "$project_namespace" wait --for=condition=complete "job/$job" --timeout="${AUDIT_TIMEOUT:-300s}" >/dev/null; then
  kubectl -n "$project_namespace" describe "job/$job" >&2 || true
  kubectl -n "$project_namespace" logs "job/$job" >&2 || true
  exit 1
fi

kubectl -n "$project_namespace" logs "job/$job" | tee "$report_path"
python3 - "$report_path" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)
required = {"missingActual", "untrackedManaged", "associationDrift", "ownershipTagDrift"}
missing = required - report.get("summary", {}).keys()
if missing:
    raise SystemExit("audit report is missing summary fields: " + ", ".join(sorted(missing)))
print("vpc-drift-audit-ok summary=" + json.dumps(report["summary"], sort_keys=True))
PY
