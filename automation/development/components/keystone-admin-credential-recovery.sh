#!/usr/bin/env bash
set -euo pipefail

operation=${1:?deploy or verify}
: "${DEVELOPMENT_NAMESPACE:?}"
root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)

case "$operation" in
  deploy)
    kubectl annotate namespace "$DEVELOPMENT_NAMESPACE" \
      dcn.ssu.ac.kr/component-mode=contract-only --overwrite >/dev/null
    kubectl -n "$DEVELOPMENT_NAMESPACE" create configmap keystone-admin-credential-recovery-contract \
      --from-literal=secret-transport=stdin \
      --from-literal=mutation-boundary=keystone-identity-backend \
      --dry-run=client -o yaml | kubectl apply -f -
    ;;
  verify)
    test "$(kubectl get namespace "$DEVELOPMENT_NAMESPACE" -o jsonpath='{.metadata.annotations.dcn\.ssu\.ac\.kr/component-mode}')" = contract-only
    test "$(kubectl -n "$DEVELOPMENT_NAMESPACE" get configmap keystone-admin-credential-recovery-contract -o jsonpath='{.data.secret-transport}')" = stdin
    bash -n "$root/deploy/scripts/reconcile-keystone-admin-credential.sh"
    python3 "$root/deploy/tests/test_keystone_admin_credential.py"
    ;;
  *) exit 2 ;;
esac
