# Fresh Server Rebuild Automation

This directory rebuilds the DCN Kubernetes management platform and its
OpenStack control plane from Ubuntu Server 24.04 hosts. It is the entry point
for a disaster rebuild; `deploy/` remains the immutable OpenStack release
reconciler.

## Safety and scope

- Run from a separate Ansible control host with console access to every node.
- `eno1` is the management and Internet interface. Automation never enslaves it.
- `eno2` is reserved for the OpenStack provider bridge (`br-ex`). The base
  playbooks validate it but do not change Netplan or OVS connectivity.
- No disk is erased automatically. Rook-Ceph requires an explicit stable disk
  identifier and a second, separately approved storage command.
- No plaintext secret belongs in Git. Supply the SOPS age identity through
  `SOPS_AGE_KEY_FILE` from offline media.
- The two-node profile reproduces the PoC but cannot provide majority quorum
  after a controller loss. Production requires at least three control-plane,
  etcd, and Ceph failure domains.

## Quick start

```bash
cd automation/ansible
cp -a inventory/poc-two-node inventory/local
# Edit inventory/local/hosts.yml and group_vars/all.yml.
./bin/preflight.sh inventory/local
ALLOW_DIRTY_REBUILD_INPUTS=0 ../bin/verify-inputs.sh

ansible-playbook -i inventory/local/hosts.yml playbooks/10-hosts.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/15-dns.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/20-kubernetes.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/30-cluster-baseline.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/35-provider-uplinks.yml

export SOPS_AGE_KEY_FILE=/media/offline/dcn-cloud.agekey
ansible-playbook -i inventory/local/hosts.yml playbooks/40-platform.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/50-openstack.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/60-verify.yml
```

Use `playbooks/site.yml` only after each phase has been rehearsed. Stateful
phases intentionally require confirmation variables described in the
inventory and runbook.

The authoritative sequence, gates, rollback points, and acceptance tests are
in [the rebuild runbook](../docs/fresh-server-rebuild-runbook.md).

`verify-inputs.sh` rejects a dirty checkout by default and validates every
locked chart checksum and metadata field. Set `ALLOW_DIRTY_REBUILD_INPUTS=1`
only while developing the automation, never for an accepted rebuild.
