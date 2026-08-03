#!/usr/bin/env bash
set -euo pipefail

repo=${MAGNUM_CAPI_GITOPS_REPO_PATH:-}
revision=${MAGNUM_CAPI_GITOPS_REVISION:-}

test -n "$repo" || { echo "MAGNUM_CAPI_GITOPS_REPO_PATH is required" >&2; exit 1; }
test -n "$revision" || { echo "MAGNUM_CAPI_GITOPS_REVISION is required" >&2; exit 1; }
test -d "$repo/.git" || { echo "missing magnum-capi-gitops checkout: $repo" >&2; exit 1; }
test "$(git -C "$repo" rev-parse HEAD)" = "$revision" || {
  echo "magnum-capi-gitops revision mismatch" >&2
  exit 1
}
test -z "$(git -C "$repo" status --porcelain)" || {
  echo "magnum-capi-gitops checkout is dirty" >&2
  exit 1
}

MAGNUM_CAPI_GITOPS_REVISION="$revision" "$repo/reconcile-platform.sh"
