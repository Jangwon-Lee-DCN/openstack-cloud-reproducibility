#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ansible_root="$root/automation/ansible"

for command in ansible-playbook ansible-lint yamllint; do
  command -v "$command" >/dev/null || {
    echo "missing automation validation command: $command" >&2
    exit 1
  }
done

cd "$ansible_root"
for playbook in playbooks/*.yml; do
  ansible-playbook -i inventory/poc-two-node/hosts.yml \
    --syntax-check "$playbook" >/dev/null
done

ansible-lint playbooks roles
yamllint -d \
  '{extends: default, rules: {line-length: disable, truthy: disable}}' \
  playbooks roles inventory/production inventory/poc-two-node

bash -n bin/*.sh ../bin/*.sh ../lab/*.sh
ALLOW_DIRTY_REBUILD_INPUTS=${ALLOW_DIRTY_REBUILD_INPUTS:-1} \
  "$root/automation/bin/verify-inputs.sh"

echo "rebuild automation validation passed"
