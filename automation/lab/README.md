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

`create.sh` downloads the official Ubuntu 24.04 release cloud image and
verifies it against the same directory's published `SHA256SUMS` before Glance
upload. Override `UBUNTU_IMAGE_BASE_URL` only with another reviewed, immutable
Ubuntu release directory.

After creation, obtain addresses with:

```bash
./run.sh status
```

Copy `inventory/rehearsal/hosts.yml` from the printed addresses, run phases
`00`, `10`, `15`, `20`, `30`, and `35`, and keep Ceph disk confirmation false.
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

## Destroy

```bash
./run.sh destroy
```

The destroy action targets only exact `rebuild-lab-*` names. It removes the
three servers, their Floating IPs, router interfaces, subnet, network, security
group, keypair, and flavor. The shared Ubuntu image is retained by default;
set `DELETE_LAB_IMAGE=1` to remove it as well.
