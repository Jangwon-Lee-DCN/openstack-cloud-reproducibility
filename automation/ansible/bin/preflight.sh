#!/usr/bin/env bash
set -euo pipefail

inventory=${1:-inventory/local}
test -f "$inventory/hosts.yml" || { echo "missing $inventory/hosts.yml" >&2; exit 1; }
command -v ansible-playbook >/dev/null || { echo "install ansible-core first" >&2; exit 1; }
ansible-inventory -i "$inventory/hosts.yml" --graph
ansible-playbook -i "$inventory/hosts.yml" playbooks/00-preflight.yml --check
