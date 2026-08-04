#!/usr/bin/env bash
set -euo pipefail

root=${1:?usage: verify-overlay.sh EXTRACTED_MAGNUM_UI_ROOT}
cluster_root="$root/magnum_ui/static/dashboard/container-infra/clusters"

python3 -m py_compile "$(dirname "$0")/enhance_magnum_ui.py"
grep -q 'Provisioning timeline' "$cluster_root/details/overview.html"
grep -q 'Approved for deployment' "$cluster_root/details/overview.controller.js"
grep -q 'GitOps ownership' "$cluster_root/details/overview.html"
grep -q 'Profile compatibility' "$cluster_root/details/overview.html"
grep -q 'Diagnosis and recovery' "$cluster_root/details/overview.html"
grep -q 'Download Kubeconfig' "$cluster_root/actions.module.js"
grep -q 'Scale Worker Node Group' "$cluster_root/actions.module.js"
grep -q 'Rolling Kubernetes Upgrade' "$cluster_root/actions.module.js"

echo 'Magnum operational UI overlay verified'
