# Kubernetes and OpenStack Node Expansion Guide

This guide adds a control-plane node or a worker-based OpenStack compute node
to an already rebuilt cluster. Keep the existing first control-plane host as
`control_plane[0]`: it generates fresh, short-lived kubeadm join data and
uploads the control-plane certificates for each expansion run.

## Common prerequisites

The new host must satisfy the same contract as a rebuild host:

- Ubuntu Server 24.04, management SSH, passwordless sudo, and time sync;
- the configured management and provider interfaces with distinct names;
- no address or route on the provider interface;
- access to package and image sources and the Kubernetes API VIP/FQDN;
- matching MTU, upstream VLAN, DNS, and NTP configuration;
- console/BMC access before applying provider-network changes.

Production compute nodes must expose `/dev/kvm`. The preflight now rejects a
production host carrying the `compute` role when hardware virtualization is
unavailable.

Back up `inventory/local`, record the current nodes and etcd membership, and
run from the same accepted Git revisions and control host used for the rebuild.

## Add one control-plane node

Append the new node after all existing members in the `control_plane` group.
Do not place it first or reorder the current first controller during the join.

```yaml
all:
  children:
    control_plane:
      hosts:
        controller-0: # existing bootstrap controller
          # existing values remain unchanged
        controller-1:
          # existing values remain unchanged
        controller-2:
          # existing values remain unchanged
        controller-3:
          ansible_host: 192.0.2.13
          node_ip: 192.0.2.13
          node_roles: [controller, ovn_gateway]
```

`ovn_gateway` is optional. Include it only when the node is wired and approved
to host the OVN gateway/OVS roles. Assign `dns_role` only when intentionally
changing the primary/secondary DNS design.

Run the inventory and host gates, then rerun the idempotent phases against the
complete inventory:

```bash
cd /srv/openstack-cloud-reproducibility/automation/ansible

ansible controller-3 -i inventory/local/hosts.yml -m ping
ansible-playbook -i inventory/local/hosts.yml playbooks/00-preflight.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/10-hosts.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/15-dns.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/20-kubernetes.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/30-cluster-baseline.yml
```

Phase 10 must see the complete inventory so every HAProxy configuration learns
the new API backend. Phase 15 updates authoritative records and resolver
configuration. Phase 20 skips initialized members, creates a fresh two-hour
join token and certificate key on `control_plane[0]`, and joins only the new
host because existing nodes already have their kubeconfig files.

If the node is an OVN gateway, inspect and approve its provider candidate:

```bash
ansible-playbook -i inventory/local/hosts.yml \
  playbooks/35-provider-uplinks.yml --limit controller-3 --check --diff
# After console, VLAN, MTU, address, route, and rollback review:
ansible-playbook -i inventory/local/hosts.yml \
  playbooks/35-provider-uplinks.yml --limit controller-3 \
  -e confirm_provider_bridge_change=true
```

Validate membership and availability:

```bash
kubectl --kubeconfig artifacts/admin.conf get nodes -o wide
kubectl --kubeconfig artifacts/admin.conf -n kube-system get pods -o wide

ansible controller-0 -i inventory/local/hosts.yml -b -m shell -a \
  'KUBECONFIG=/etc/kubernetes/admin.conf kubectl -n kube-system exec \
  etcd-controller-0 -- etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key member list'
```

Replace the static etcd Pod name in the example if the bootstrap controller
has another hostname. Verify API availability while stopping HAProxy or
Keepalived on one node at a time.

An odd etcd member count is preferred. Expanding two members to three improves
quorum behavior. Expanding three members to four does not increase tolerated
failures (both require a quorum of three); add two nodes and reach five when
the goal is greater control-plane fault tolerance.

## Add a worker-based compute node

Yes: a host declared only under `workers` with `node_roles: [compute]` joins as
a Kubernetes worker and becomes an OpenStack compute node. It does not join
etcd and does not receive the Kubernetes control-plane taint.

```yaml
all:
  children:
    workers:
      hosts:
        compute-2:
          ansible_host: 192.0.2.22
          node_ip: 192.0.2.22
          node_roles: [compute]
```

The automation applies the pinned charts' canonical selectors:

```text
openstack-compute-node=enabled
openvswitch=enabled
```

Add `ovn_gateway` only if this compute node must also provide external/provider
gateway service. That role additionally applies:

```text
openstack-network-gateway=enabled
openstack-network-node=enabled
l3-agent=enabled
```

Do not add the host to `ceph_nodes` unless it owns a separately reviewed Ceph
device. A compute-only expansion does not require `confirm_ceph_device_wipe`.

Run:

```bash
cd /srv/openstack-cloud-reproducibility/automation/ansible

ansible compute-2 -i inventory/local/hosts.yml -m ping
ansible-playbook -i inventory/local/hosts.yml playbooks/00-preflight.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/10-hosts.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/15-dns.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/20-kubernetes.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/30-cluster-baseline.yml

ansible-playbook -i inventory/local/hosts.yml \
  playbooks/35-provider-uplinks.yml --limit compute-2 --check --diff
# After the provider-network safety review:
ansible-playbook -i inventory/local/hosts.yml \
  playbooks/35-provider-uplinks.yml --limit compute-2 \
  -e confirm_provider_bridge_change=true
```

Kubernetes DaemonSets react to the new node and labels. Rerun Phase 50 from the
control host to reconcile the accepted OpenStack release and Phase 60 to catch
placement or registration failures:

```bash
export SOPS_AGE_KEY_FILE=/media/offline/dcn-cloud.agekey
ansible-playbook -i inventory/local/hosts.yml playbooks/50-openstack.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/60-verify.yml
```

Acceptance requires more than a Ready Kubernetes node. Confirm:

```bash
kubectl --kubeconfig artifacts/admin.conf get node compute-2 --show-labels
openstack hypervisor list
openstack compute service list --service nova-compute
```

Then boot a disposable VM explicitly on the new hypervisor, verify tenant and
provider networking, metadata, security groups, SNAT/Floating IP, live or cold
migration as supported, and Cinder attachment. Check that OVN controller and
OVS are healthy on the host and that Nova reports the expected vCPU, RAM, and
disk inventory.

## Role-to-label contract

| Inventory role | Canonical labels |
| --- | --- |
| `controller` in `control_plane` | `openstack-control-plane=enabled` |
| `compute` | `openstack-compute-node=enabled`, `openvswitch=enabled` |
| `ovn_gateway` | `openstack-network-gateway=enabled`, `openstack-network-node=enabled`, `openvswitch=enabled`, `l3-agent=enabled` |
| `cinder` | `openstack-cinder-volume=enabled` |
| `object_storage` | `openstack-object-storage=enabled` |

These labels are matched to the pinned Nova, Neutron, OVN, and Open vSwitch
chart selectors. Do not substitute similarly named labels without checking the
accepted chart packages.

`automation/bin/verify-automation.sh` includes a synthetic four-controller,
one-compute, three-storage inventory test. It verifies the init/control-plane/
worker join target sets, every HAProxy API backend, positive and negative KVM
gates, and the canonical selectors in the pinned Nova, OVN, and Open vSwitch
charts. Run it before accepting an inventory or expansion-automation change.
