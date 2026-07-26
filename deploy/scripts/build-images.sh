#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
NAMESPACE=${NAMESPACE:-openstack}

for command in kubectl sops; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done

sops -d "$REPO_ROOT/deploy/secrets/telemetry-harbor-push.secret.sops.yaml"   | kubectl apply -f -

for component in gnocchi ceilometer aodh; do
  kubectl create configmap "${component}-image-build" -n "$NAMESPACE"     --from-file="Dockerfile=$REPO_ROOT/images/$component/Dockerfile"     --dry-run=client -o yaml | kubectl apply -f -
  kubectl delete job "${component}-image-build" -n "$NAMESPACE"     --ignore-not-found
  kubectl apply -f "$REPO_ROOT/deploy/manifests/${component}-image-build.yaml"
  kubectl wait -n "$NAMESPACE" --for=condition=complete     "job/${component}-image-build" --timeout=20m
  digest=$(kubectl get pod -n "$NAMESPACE" -l "job-name=${component}-image-build"     -o jsonpath='{.items[0].status.containerStatuses[0].state.terminated.message}')
  printf '%s image digest: %s
' "$component" "$digest"
done

cat <<'EOF'
Compare every emitted digest with the digest pinned in deploy/values or custom
manifests. A mismatch requires a reviewed values/manifest update and commit;
do not deploy an unrecorded tag.
EOF
