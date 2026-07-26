#!/usr/bin/env bash
set -euo pipefail

NAMESPACE=${NAMESPACE:-openstack}
PUBLIC_HOST=${PUBLIC_HOST:-cloud.dcn.ssu.ac.kr}
PUBLIC_GATEWAY_IP=${PUBLIC_GATEWAY_IP:-192.168.21.6}

kubectl get deployments,daemonsets,poddisruptionbudgets -n "$NAMESPACE"   | grep -E 'ceilometer|gnocchi|aodh'
kubectl get pods -n "$NAMESPACE" -o wide   | grep -E 'ceilometer|gnocchi|aodh'

for release in ceilometer aodh; do
  helm status "$release" -n "$NAMESPACE" >/dev/null
  printf '%s Helm release: deployed
' "$release"
done

for path in metric alarming; do
  code=$(curl --max-time 10 -ksS --resolve     "$PUBLIC_HOST:443:$PUBLIC_GATEWAY_IP" -o /dev/null -w '%{http_code}'     "https://$PUBLIC_HOST/$path/healthcheck")
  [[ "$code" == "200" ]] || { echo "$path health failed: HTTP $code" >&2; exit 1; }
  printf '%s public health: HTTP %s
' "$path" "$code"
done

if kubectl logs -n "$NAMESPACE" deployment/ceilometer-notification   --all-pods=true --since=10m 2>&1   | grep -Eq 'Server unexpectedly closed connection|:15672/'; then
  echo 'Ceilometer notification transport regression detected' >&2
  exit 1
fi

cat <<'EOF'
Infrastructure health checks passed.
Mandatory production gate still requiring an explicit workload test:
Ceilometer sample -> Gnocchi metric/resource -> Aodh alarm evaluation.
EOF
