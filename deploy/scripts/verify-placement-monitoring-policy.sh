#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
snapshot="$root/deploy/releases/placement.values.sops.yaml"
site_values="$root/deploy/values/site/placement.yaml"

command -v sops >/dev/null || { echo "missing command: sops" >&2; exit 1; }
python3 - "$site_values" <(sops -d "$snapshot") <<'PY'
import sys
import yaml

site_path, snapshot_path = sys.argv[1:]
snapshot = yaml.safe_load(open(snapshot_path, encoding="utf-8"))
site = yaml.safe_load(open(site_path, encoding="utf-8"))
expected = {
    "placement:allocation_candidates:list",
    "placement:resource_providers:list",
    "placement:resource_providers:inventories:list",
    "placement:resource_providers:traits:list",
    "placement:resource_providers:usages",
    "placement:traits:list",
}
for label, values in (("release snapshot", snapshot), ("site values", site)):
    policy = values.get("conf", {}).get("policy", {})
    if set(policy) != expected:
        raise SystemExit(f"{label} Placement monitoring policy differs from the accepted read set")
    if set(policy.values()) != {"role:admin or role:monitoring"}:
        raise SystemExit(f"{label} Placement monitoring policy has an unexpected grant")
    forbidden = (":create", ":update", ":delete", "allocations:list")
    if any(term in rule for rule in policy for term in forbidden):
        raise SystemExit(f"{label} Placement monitoring policy includes mutation or consumer allocations")
print("Placement monitoring policy snapshot verified")
PY
