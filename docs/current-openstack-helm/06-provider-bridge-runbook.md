# Provider Bridge Runbook

## Scope

This PoC dedicates `eno2` on every gateway/compute node to the untagged
`external` Neutron provider network. Kubernetes, SSH, DNS, and the host default
route remain on `eno1`. `eno2` must have no host IP address before OVN attaches
it to `br-ex`.

The OVN chart owns `br-ex` and adds `eno2` through `conf.auto_bridge_add`.
Do not define a Linux or Netplan bridge with the same name.

## Saved State and Rollback

Before changing either host, copy `/etc/netplan` to a timestamped directory
under `/var/backups/openstack-cloud-services/`. Record `ip address`, `ip route`,
and link state. Use physical console access for the change even though `eno1`
is not modified.

Rollback consists of uninstalling OVN/Open vSwitch, restoring the saved
Netplan directory on the affected host, running `netplan generate` and
`netplan apply`, and verifying the original `eno2` address. Never move the
`eno1` address or default route during this procedure.

## Target State

| Node | Management | Provider port | OVS mapping |
| --- | --- | --- | --- |
| `cloud-controller-0` | `eno1` / `192.168.21.10` | addressless `eno2` | `external:br-ex` |
| `cloud-controller-1` | `eno1` / `192.168.21.12` | addressless `eno2` | `external:br-ex` |

Floating IPs and router gateway ports use `192.168.21.100-192.168.21.200`.
The Kubernetes Cilium load-balancer addresses `.4`, `.5`, and `.6` are outside
that pool and continue to be announced through `eno1`.
