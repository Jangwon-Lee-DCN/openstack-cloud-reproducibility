#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
app="$root/images/project-facade/app.py"
pkg="$root/images/horizon-project-selfservice-dashboard/pkg"

python3 -m py_compile \
  "$app" \
  "$pkg"/project_selfservice_dashboard/*.py \
  "$pkg"/project_selfservice_dashboard/admin/*.py \
  "$pkg"/identity_projects_patch/*.py

for route in member-candidates groups quota-usage resource-summary decommission-plan; do
  grep -q "$route" "$app"
done
grep -q 'class MembersTab' "$pkg/identity_projects_patch/tabs.py"
grep -q 'class ProjectHealthTab' "$pkg/identity_projects_patch/tabs.py"
grep -q 'class DecommissionProjectForm' "$pkg/project_selfservice_dashboard/forms.py"
grep -q 'class ProjectOperations' "$pkg/project_selfservice_dashboard/admin/panel.py"
grep -q 'ProjectFacadeUnavailable' "$root/deploy/manifests/project-management-alerts.yaml"

echo "Project management source contract passed."
