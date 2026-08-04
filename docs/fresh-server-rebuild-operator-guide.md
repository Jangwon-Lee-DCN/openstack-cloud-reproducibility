# Fresh Server Rebuild Operator Guide

This is the command-by-command operator procedure for rebuilding the platform
from newly installed Ubuntu Server 24.04 hosts. Read the design, backup, and
recovery constraints in `fresh-server-rebuild-runbook.md` before using it.

## 1. Required environment

Production requires:

- three or five control-plane/etcd nodes;
- at least three Ceph storage failure domains with dedicated empty disks;
- SSH access through the management network and passwordless sudo;
- remote console or BMC access before changing networking;
- one management/default-route NIC and one address-less provider L2 NIC on
  every applicable node;
- reserved API, public, internal, platform, and registry VIPs and FQDNs;
- frozen Pod, Service, management, provider, and external-network CIDRs;
- upstream VLAN and MTU configuration matching the site design;
- a separate Ansible control host that can resolve and route to the API VIP;
- offline backups, the SOPS age identity, SSH keys, and accepted Git revisions.

The two-vCPU/eight-GiB rehearsal VM profile only validates Kubernetes and the
automation gates. It is not an OpenStack production sizing recommendation.

Use stable `/dev/disk/by-id/...` identifiers for Ceph. Never use an OS disk,
mounted disk, or an ambiguous `/dev/sdX` name. The automation does not wipe a
disk automatically.

## 2. Prepare the control host

```bash
sudo apt-get update
sudo apt-get install -y ansible-core ansible-lint yamllint git openssh-client

sudo mkdir -p /srv
sudo chown "$USER":"$USER" /srv

git clone \
  https://github.com/Jangwon-Lee-DCN/openstack-cloud-reproducibility.git \
  /srv/openstack-cloud-reproducibility
git clone \
  https://github.com/Jangwon-Lee-DCN/openstack-cloud-services.git \
  /srv/openstack-cloud-services
git clone \
  https://github.com/Jangwon-Lee-DCN/magnum-capi-gitops.git \
  /srv/magnum-capi-gitops

cd /srv/openstack-cloud-reproducibility/automation/ansible
mkdir -p inventory/local/group_vars
cp inventory/production/hosts.example.yml inventory/local/hosts.yml
cp inventory/production/group_vars/all.example.yml \
  inventory/local/group_vars/all.yml
```

Keep the SSH private key and SOPS identity outside Git.

## 3. Fill the site inventory

Edit `inventory/local/hosts.yml`. Set `ansible_host`, `node_ip`, roles,
primary/secondary DNS roles, and a stable `ceph_device` for every storage node.
The production example shows the supported groups: `control_plane`, `workers`,
and `ceph_nodes`.

Edit `inventory/local/group_vars/all.yml` and replace every `REPLACE_...`
value. Review at least:

- `ansible_user` and the SSH private-key configuration;
- `management_interface` and `provider_interface`;
- Kubernetes API FQDN, VIP, port, Pod CIDR, and Service CIDR;
- DNS domain, reverse zone, forwarders, and zone serial;
- public, internal, platform, and registry FQDNs and VIPs;
- external network CIDR, gateway, and allocation pool;
- repository paths and the approved `services_repo_ref`;
- `keepalived_auth_pass`.

Leave both destructive approval variables false initially:

```yaml
confirm_ceph_device_wipe: false
confirm_provider_bridge_change: false
```

## 4. Validate all inputs

```bash
cd /srv/openstack-cloud-reproducibility/automation/ansible

ansible all -i inventory/local/hosts.yml -m ping
./bin/preflight.sh inventory/local
ALLOW_DIRTY_REBUILD_INPUTS=0 ../bin/verify-inputs.sh

cd /srv/openstack-cloud-reproducibility
ALLOW_DIRTY_REBUILD_INPUTS=0 automation/bin/verify-automation.sh
```

Do not continue after a failed gate. The verification requires an accepted,
clean reproducibility checkout and validates the 25 pinned Helm packages.

## 5. Build the host and Kubernetes layers

Run each phase separately from the Ansible directory:

```bash
cd /srv/openstack-cloud-reproducibility/automation/ansible

ansible-playbook -i inventory/local/hosts.yml playbooks/00-preflight.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/10-hosts.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/15-dns.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/20-kubernetes.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/30-cluster-baseline.yml
```

Phase 20 fetches the administrative kubeconfig to the ignored
`automation/ansible/artifacts/admin.conf` file on the control host. Confirm
that the control host resolves the configured API FQDN, routes to its VIP, and
receives `ok` from `/readyz` before continuing.

Run the disposable all-node connectivity test:

```bash
ansible controller-0 \
  -i inventory/local/hosts.yml \
  -b -m script \
  -a 'bin/verify-kubernetes-network.sh executable=/bin/bash'
```

Also confirm that all nodes are Ready, all etcd members are healthy, both DNS
servers answer, and the API remains available during a controlled VIP-owner
failover.

## 6. Approve the provider uplink

Render and inspect without applying:

```bash
ansible-playbook \
  -i inventory/local/hosts.yml \
  playbooks/35-provider-uplinks.yml --check --diff
```

On every applicable node, confirm that the provider NIC has no address or
route. Verify the switch VLAN mode and MTU, prepare console access and a timed
rollback, then set `confirm_provider_bridge_change: true` and apply:

```bash
ansible-playbook \
  -i inventory/local/hosts.yml \
  playbooks/35-provider-uplinks.yml
```

Confirm that management SSH and the default route still use the management
NIC. Later verify `br-ex`, OVS/OVN chassis registration, OpenFlow, ARP, and
provider egress.

## 7. Approve Ceph devices

Inspect every declared device on its storage node:

```bash
lsblk -e7 -o NAME,SIZE,MODEL,SERIAL,FSTYPE,MOUNTPOINTS
sudo wipefs -n /dev/disk/by-id/REVIEWED_DEVICE_ID
```

Match model, serial, size, filesystem, mounts, and the inventory stable ID.
Disk wiping is a separate human-approved operation. Only after every selected
disk is empty and reviewed, set `confirm_ceph_device_wipe: true`.

Production Rook values must retain at least three failure domains, MON count
three, and replica/min-size policy 3/2. Review the rendered
`/tmp/dcn-rook-values.yaml` during the platform phase.

## 8. Install platform prerequisites

Mount the offline identity on the control host:

```bash
export SOPS_AGE_KEY_FILE=/media/offline/dcn-cloud.agekey
test -r "$SOPS_AGE_KEY_FILE"

cd /srv/openstack-cloud-reproducibility/automation/ansible
ansible-playbook -i inventory/local/hosts.yml playbooks/40-platform.yml
```

The phase checks the fetched kubeconfig, API readiness, services-repository
revision, readable SOPS identity, and Ceph approval before mutation. It then
installs the security, storage, Gateway, registry, observability, and Octavia
jobboard prerequisites in dependency order.

## 9. Install the pinned OpenStack control plane

Keep `SOPS_AGE_KEY_FILE` exported and run:

```bash
ansible-playbook -i inventory/local/hosts.yml playbooks/50-openstack.yml
```

This verifies immutable inputs, reconciles the pinned OpenStack-Helm stack,
and installs Designate/PowerDNS, CAPI/CAPO/ORC, the add-on provider, workload
chart repository, and Magnum integration.

## 10. Run acceptance

```bash
ansible-playbook -i inventory/local/hosts.yml playbooks/60-verify.yml
```

Create a disposable project and verify Keystone authentication, Glance image
upload, VM boot and metadata, security groups, overlapping VPC CIDRs, SNAT and
Floating IP, Cinder attach/write/reboot, Heat, Designate, Barbican, OVN and
Amphora load balancers, and a Magnum workload cluster. For the workload,
verify a Kubernetes LoadBalancer Service uses the Octavia `ovn` provider with
`SOURCE_IP_PORT` and serves real traffic through its floating IP. Repeat critical checks
while draining or powering off controllers and storage nodes one at a time.

Record the inventory commit/bundle checksums, Git revisions, command logs,
failure-test results, RTO/RPO, and alert delivery evidence.

## 11. Re-run and recovery rules

After an accepted first run, re-run phases individually to check convergence.
Do not use `playbooks/site.yml` until every phase and destructive gate has been
rehearsed for the site.

This process creates a clean, empty cloud. It does not restore tenant data.
Restoring retained Ceph, MariaDB, etcd, RGW, secrets, images, volumes, or
load-balancer state requires a consistent backup and a separate recovery plan.
Never point the clean-build procedure at retained production disks.

For post-build control-plane and compute capacity expansion, follow
[`node-expansion-operator-guide.md`](node-expansion-operator-guide.md).
