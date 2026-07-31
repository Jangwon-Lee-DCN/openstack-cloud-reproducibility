#!/usr/bin/env bash
set -euo pipefail

ansible_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
work=$(mktemp -d /tmp/rebuild-expansion-contract.XXXXXX)
trap 'rm -rf -- "$work"' EXIT

inventory="$work/hosts.yml"
cat >"$inventory" <<'YAML'
---
all:
  vars:
    ansible_connection: local
    deployment_profile: production
    allow_poc_quorum: false
    keepalived_auth_pass: testpass
  children:
    control_plane:
      hosts:
        controller-0: {ansible_host: 192.0.2.10, node_ip: 10.0.0.10}
        controller-1: {ansible_host: 192.0.2.11, node_ip: 10.0.0.11}
        controller-2: {ansible_host: 192.0.2.12, node_ip: 10.0.0.12}
        controller-3: {ansible_host: 192.0.2.13, node_ip: 10.0.0.13}
    workers:
      hosts:
        compute-2:
          ansible_host: 192.0.2.22
          node_ip: 10.0.0.22
          node_roles: [compute]
    ceph_nodes:
      hosts:
        storage-0: {}
        storage-1: {}
        storage-2: {}
YAML

cd "$ansible_root"
ansible-playbook -i "$inventory" playbooks/20-kubernetes.yml --list-hosts \
  >"$work/join-hosts.txt"

python3 - "$work/join-hosts.txt" <<'PY'
import pathlib
import sys

text = pathlib.Path(sys.argv[1]).read_text()
sections = text.split("  play #")
expected = [
    ("Initialize the first Kubernetes control plane", {"controller-0"}),
    ("Join the remaining control-plane nodes", {"controller-1", "controller-2", "controller-3"}),
    ("Join worker and storage-only nodes", {"compute-2", "storage-0", "storage-1", "storage-2"}),
]
for title, hosts in expected:
    section = next((part for part in sections if title in part), None)
    if section is None:
        raise SystemExit(f"missing expansion play: {title}")
    actual = {
        line.strip() for line in section.splitlines()
        if line.startswith("      ") and not line.strip().startswith("pattern:")
    }
    if actual != hosts:
        raise SystemExit(f"{title}: expected {sorted(hosts)}, got {sorted(actual)}")
PY

ansible localhost -c local -i "$inventory" \
  -m ansible.builtin.template \
  -a "src=roles/api_load_balancer/templates/haproxy.cfg.j2 dest=$work/haproxy.cfg" \
  -e kubernetes_api_port=8443 >/dev/null

for host in controller-0 controller-1 controller-2 controller-3; do
  grep -q "server $host " "$work/haproxy.cfg"
done
[[ $(grep -c '^  server controller-' "$work/haproxy.cfg") -eq 4 ]]

python3 - "$inventory" <<'PY'
import pathlib
import sys
import yaml

data = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text())
children = data["all"]["children"]
compute = children["workers"]["hosts"]["compute-2"]
assert compute["node_roles"] == ["compute"]
assert "compute-2" not in children["control_plane"]["hosts"]
PY

ansible-playbook -i "$inventory" playbooks/00-preflight.yml \
  --start-at-task 'Inspect hardware virtualization for production compute nodes' \
  >/dev/null

set +e
ansible-playbook -i "$inventory" playbooks/00-preflight.yml \
  --start-at-task 'Inspect hardware virtualization for production compute nodes' \
  -e compute_kvm_device=/definitely/missing \
  >"$work/missing-kvm.txt" 2>&1
missing_kvm_rc=$?
set -e
[[ $missing_kvm_rc -ne 0 ]]
grep -q 'A production compute node requires /dev/kvm' "$work/missing-kvm.txt"

echo "node expansion contract verification passed"
