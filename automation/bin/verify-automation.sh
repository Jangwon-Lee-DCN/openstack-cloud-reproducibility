#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ansible_root="$root/automation/ansible"

for command in ansible-playbook ansible-lint awk grep tar yamllint; do
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
bin/verify-expansion-contract.sh
ALLOW_DIRTY_REBUILD_INPUTS=${ALLOW_DIRTY_REBUILD_INPUTS:-1} \
  "$root/automation/bin/verify-inputs.sh"

role_tasks="$ansible_root/roles/cluster_baseline/tasks/main.yml"
nova_chart="$root/helm/packages/patched/nova-2026.1.0.tgz"
ovn_chart="$root/helm/packages/patched/ovn-2026.1.0.tgz"
ovs_chart="$root/helm/packages/upstream/openvswitch-2026.1.0.tgz"

grep -q 'openstack-compute-node=enabled' "$role_tasks"
grep -q 'openvswitch=enabled' "$role_tasks"
tar -xOf "$nova_chart" --wildcards '*/values.yaml' | \
  awk '/node_selector_key: openstack-compute-node/{found=1} END{exit !found}'
tar -xOf "$ovn_chart" --wildcards '*/values.yaml' | \
  awk '/node_selector_key: openstack-network-node/{found=1} END{exit !found}'
tar -xOf "$ovs_chart" --wildcards '*/values.yaml' | \
  awk '/node_selector_key: openvswitch/{found=1} END{exit !found}'

echo "rebuild automation validation passed"
