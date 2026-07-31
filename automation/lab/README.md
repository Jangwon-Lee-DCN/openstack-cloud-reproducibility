# Three-VM Rebuild Rehearsal

This lab validates the fresh-host Ansible phases without risking physical
controllers. It creates three Ubuntu 24.04 VMs in an isolated OpenStack
network. The VMs are intentionally sized for Ubuntu, kubeadm, Cilium, BIND,
and Ansible testing; they are not large enough to benchmark the complete
nested OpenStack control plane.

## Capacity

Default aggregate allocation:

- 6 vCPUs
- 24 GiB RAM
- 120 GiB thin-provisioned root disk
- three Floating IPs

The accepted cloud had 24 physical vCPUs, 62.7 GiB Nova RAM, no running VMs,
and approximately 881 GiB free Ceph space when this profile was created.

After all three rehearsal VMs were started, Nova reported 6 of 24 vCPUs,
25,088 of 64,192 MiB RAM, and 120 GiB of root disk allocated. The remaining
39,104 MiB of RAM and 774 GiB of reported free local capacity leave adequate
headroom for the host platform, but this lab must not be used for a nested
Ceph and OpenStack deployment.

## Create

The wrapper uses a short-lived OpenStack client Pod and the existing encrypted
administrator runtime Secret. The SSH private key remains outside Git.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_rebuild_lab -C rebuild-lab
cd automation/lab
LAB_PUBLIC_KEY_FILE=~/.ssh/id_ed25519_rebuild_lab.pub ./run.sh create
```

The default is three nodes. To rehearse an in-place control-plane expansion,
preserve the existing lab and increase the count; creation is idempotent and
adds only missing numbered nodes:

```bash
LAB_NODE_COUNT=4 \
LAB_PUBLIC_KEY_FILE=~/.ssh/id_ed25519_rebuild_lab.pub \
./run.sh create
LAB_NODE_COUNT=4 ./run.sh inventory \
  > ../ansible/inventory/local/hosts.yml
```

`LAB_NODE_COUNT` accepts three through five. Pass the current count to
`inventory`; `destroy` always scans the complete supported range to avoid
orphaning a node when the original count is forgotten.

To add a fifth VM as a worker-based compute rehearsal while retaining four
control-plane members:

```bash
LAB_NODE_COUNT=5 \
LAB_PUBLIC_KEY_FILE=~/.ssh/id_ed25519_rebuild_lab.pub \
./run.sh create
LAB_NODE_COUNT=5 LAB_CONTROL_PLANE_COUNT=4 ./run.sh inventory \
  > ../ansible/inventory/local/hosts.yml
```

`LAB_CONTROL_PLANE_COUNT` defaults to the total count and accepts values from
three through `LAB_NODE_COUNT`. Higher-numbered nodes are emitted under
`workers` with `node_roles: [compute]`.

`create.sh` downloads the official Ubuntu 24.04 release cloud image and
verifies it against the same directory's published `SHA256SUMS` before Glance
upload. Override `UBUNTU_IMAGE_BASE_URL` only with another reviewed, immutable
Ubuntu release directory.

After creation, obtain addresses with:

```bash
./run.sh status
```

Generate the ignored, machine-specific inventory without copying addresses by
hand:

```bash
./run.sh inventory > ../ansible/inventory/local/hosts.yml
```

Then run phases `00`, `10`, `15`, `20`, `30`, and `35`, and keep Ceph disk
confirmation false.
The lifecycle script attaches a second, subnet-less Neutron network so the
guest's second NIC can exercise the Layer 2-only provider-uplink checks without
touching its management interface. It also reserves `10.77.0.250` and adds it
as an allowed-address pair on all management ports for the Keepalived API VIP.

## Verified rehearsal

The 2026-07-31 rehearsal completed phases `00`, `10`, `15`, `20`, `30`, and
the non-mutating checks in `35`:

- all three Ubuntu VMs joined the Kubernetes `v1.36.3` control plane and the
  three stacked etcd members remained healthy;
- Cilium `1.19.5`, CoreDNS, Hubble Relay, and Hubble UI reached Ready;
- BIND primary and secondary both answered the API name and every management
  link preferred the two internal resolvers, including forwarded Internet
  lookups;
- the Kubernetes API VIP moved from `rebuild-lab-0` to `rebuild-lab-1` when
  Keepalived was stopped on the owner, and `/readyz` continued to return `ok`;
- every `ens8` provider interface passed the no-address and no-route safety
  assertions. The bridge candidate was rendered only, as intended.
- stopping primary BIND left both internal and forwarded Internet resolution
  available through the secondary, and the primary returned cleanly;
- rebooting a non-VIP control-plane VM preserved API availability and the node,
  kubelet, CRI-O, Cilium, and its etcd member returned healthy automatically;
- the disposable network verifier passed all nine cross-node client-to-Pod-IP
  paths and all three client-to-ClusterIP paths.

This run also verified why `ansible_host` and `node_ip` are separate inventory
fields: Ansible reaches these VMs through Floating IPs, while BIND, HAProxy,
Keepalived, kubelet, and etcd must advertise the tenant-network node addresses.

The same day, the lab was then fully destroyed and recreated with three fresh
Ubuntu instances and new Neutron ports and addresses. The second clean run
again completed phases `00` through `35`, proving that the first result did not
depend on retained VM disks or Kubernetes state. This lifecycle test also found
and fixed two rehearsal-tool assumptions: Floating IP cleanup now discovers
addresses through each server port (the client has no `floating ip list
--server` option), and the network verifier automatically uses the node's
administrative kubeconfig when invoked remotely as root.

The recreated cluster also passed the failure suite independently: stopping
primary BIND left authoritative and forwarded queries available from the
secondary; stopping Keepalived on the VIP owner moved `10.77.0.250` to the next
controller while `/readyz` remained available from every node; and rebooting a
non-owner controller returned its node, stacked etcd member, Cilium agent,
kubelet, CRI-O, HAProxy, and Keepalived to healthy state in 74 seconds. The
post-reboot network test again passed all nine Pod-IP paths and all three
ClusterIP paths. Final consistency checks found exactly one VIP owner, no
failed systemd units, no etcd alarms, all three etcd members started, and a
healthy Cilium status. Kubeadm reported one year remaining on leaf certificates
and nine years on the cluster certificate authorities at rehearsal time.

The expansion rehearsal then raised `LAB_NODE_COUNT` from three to four without
recreating the existing instances. The generated inventory added
`rebuild-lab-3`; phases `00`, `10`, `15`, `20`, `30`, and the safe checks in
`35` joined it as a real stacked-etcd control-plane member. Existing members
were skipped by the join role, while HAProxy and BIND learned the new node.
All four etcd endpoints were healthy and the network verifier passed sixteen
Pod-IP paths plus all four ClusterIP paths. The new member rebooted and returned
its node, etcd Pod, and Cilium agent in 75 seconds, and a second phase-20 run
reported zero changes on all four members. Four etcd members still tolerate
only one failure; this topology validates expansion mechanics rather than an
HA improvement over three members.

A fifth VM was then emitted under `workers` with `node_roles: [compute]`. It
joined through the worker role without entering etcd, remained untainted, and
received `openstack-compute-node=enabled` and `openvswitch=enabled` without the
OVN gateway label. The provider-interface safety gate passed, all twenty-five
Pod-IP paths and all five ClusterIP paths succeeded, and the worker returned
Ready with Cilium after a 32-second reboot. Phase 20 then converged with zero
changes on all five nodes. This run also found a multi-port OpenStack client
ambiguity: Floating IP creation now binds explicitly to the management port
instead of asking the client to choose between management and address-less
provider ports.

The compute worker also exercised the normally gated phase-35 mutation. After
the candidate review, the approved Netplan installed successfully, retained
the management default route on `ens3`, and kept `ens8` free of addresses and
routes. A second run reported zero changes. After another reboot the Netplan,
SSH path, kubelet, CRI-O, and Kubernetes Ready state all persisted.

## Destroy

```bash
./run.sh destroy
```

The destroy action targets only exact `rebuild-lab-*` names. It removes the
three servers, their Floating IPs, router interfaces, subnet, network, security
group, keypair, and flavor. The shared Ubuntu image is retained by default;
set `DELETE_LAB_IMAGE=1` to remove it as well.
