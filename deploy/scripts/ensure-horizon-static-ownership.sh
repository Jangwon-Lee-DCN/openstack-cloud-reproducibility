#!/usr/bin/env bash
set -euo pipefail

NAMESPACE=${NAMESPACE:-openstack}

for command in kubectl python3; do
  command -v "$command" >/dev/null || {
    echo "missing command: $command" >&2
    exit 1
  }
done

# The chart runs collectstatic/compress as root, then serves Horizon through a
# WSGI daemon running as the horizon user. With COMPRESS_OFFLINE=False the
# runtime compressor must be able to create cache files below STATIC_ROOT.
# Patch the chart-generated script idempotently after every Helm reconciliation.
kubectl get configmap horizon-bin -n "$NAMESPACE" -o json \
  | python3 -c '
import json
import sys

document = json.load(sys.stdin)
script = document["data"]["horizon.sh"]
marker = "chown -R horizon:horizon /var/www/html/horizon"
if marker not in script:
    needle = "  /tmp/manage.py compress --force\n"
    if script.count(needle) != 1:
        raise SystemExit("unexpected horizon.sh compress command")
    script = script.replace(
        needle,
        needle
        + "  # Allow the Horizon WSGI user to write runtime compressor cache files.\n"
        + f"  {marker}\n",
    )
    document["data"]["horizon.sh"] = script
json.dump(document, sys.stdout)
' \
  | kubectl replace -f -

kubectl rollout restart deployment/horizon -n "$NAMESPACE"
