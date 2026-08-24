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

set +e
low_count_output=$(UBUNTU_IMAGE_BASE_URL=x LAB_NODE_COUNT=2 \
  ../lab/remote.sh status 2>&1)
low_count_rc=$?
high_control_output=$(UBUNTU_IMAGE_BASE_URL=x LAB_NODE_COUNT=5 \
  LAB_CONTROL_PLANE_COUNT=6 ../lab/remote.sh status 2>&1)
high_control_rc=$?
set -e
[[ $low_count_rc -eq 2 && $low_count_output == *"between 3 and 5"* ]]
[[ $high_control_rc -eq 2 && $high_control_output == *"between 3 and LAB_NODE_COUNT"* ]]

ALLOW_DIRTY_REBUILD_INPUTS=${ALLOW_DIRTY_REBUILD_INPUTS:-1} \
  "$root/automation/bin/verify-inputs.sh"

role_tasks="$ansible_root/roles/cluster_baseline/tasks/main.yml"
nova_chart="$root/helm/packages/patched/nova-2026.1.0.tgz"
ovn_chart="$root/helm/packages/patched/ovn-2026.1.0.tgz"
ovs_chart="$root/helm/packages/upstream/openvswitch-2026.1.0.tgz"

grep -q 'openstack-compute-node=enabled' "$role_tasks"
grep -q 'openvswitch=enabled' "$role_tasks"
grep -q 'Phase 67 must be limited to an explicitly approved GPU host' \
  "$ansible_root/playbooks/67-gpu-vfio-passthrough.yml"
grep -q '/etc/initramfs-tools/modules' \
  "$ansible_root/roles/gpu_vfio_passthrough/tasks/main.yml"
grep -q 'pci_passthrough:alias=rtx3090ti:1,rtx3090ti-audio:1' \
  "$root/deploy/scripts/reconcile-preview-service-catalog.sh"
python3 - "$root/deploy/values/site/nova.yaml" <<'PY'
import sys
import yaml

nova = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))["conf"]["nova"]
pci = nova["pci"]
assert pci["report_in_placement"] is False
assert len(pci["device_spec"]) == 2
assert len(pci["alias"]) == 2
filters = nova["filter_scheduler"]["enabled_filters"]
assert "NUMATopologyFilter" in filters
assert "PciPassthroughFilter" in filters
PY
tar -xOf "$nova_chart" --wildcards '*/values.yaml' | \
  awk '/node_selector_key: openstack-compute-node/{found=1} END{exit !found}'
tar -xOf "$ovn_chart" --wildcards '*/values.yaml' | \
  awk '/node_selector_key: openstack-network-node/{found=1} END{exit !found}'
tar -xOf "$ovs_chart" --wildcards '*/values.yaml' | \
  awk '/node_selector_key: openvswitch/{found=1} END{exit !found}'

echo "rebuild automation validation passed"
