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
Nested VMs have only one tenant NIC by default, so provider-uplink validation
requires adding a second Neutron port to each VM or limiting the rehearsal to
the Kubernetes baseline.

## Destroy

```bash
./run.sh destroy
```

The destroy action targets only exact `rebuild-lab-*` names. It removes the
three servers, their Floating IPs, router interfaces, subnet, network, security
group, keypair, and flavor. The shared Ubuntu image is retained by default;
set `DELETE_LAB_IMAGE=1` to remove it as well.
