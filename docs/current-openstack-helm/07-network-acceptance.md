# Neutron Network Acceptance Test

## 2026-07-25 PoC Result

The first full tenant-network test passed after two integration defects were corrected:

1. Nova os-vif required the local OVSDB endpoint at `127.0.0.1:6640`. OVSDB is now bound only to loopback, not to an externally reachable address.
2. OVN runs as UID 42424 while the PoC OVS process runs as root. A lifecycle watcher restores ownership of recreated `br-int.mgmt` sockets so OVN can continue programming flows after OVS restarts.

Validated resources:

- Tenant network: `poc-egress-net` (`10.42.0.0/24`, Geneve, MTU 1442)
- Router: `poc-egress-router`, SNAT enabled
- Router external address: `192.168.21.153`
- VM: `poc-egress-vm`, fixed address `10.42.0.144`, hosted on `cloud-controller-0`
- Floating IP: `192.168.21.200`
- Security group: `poc-egress-sg` with ingress ICMP and TCP/22

Validated from inside the VM:

- DHCP address and default route via `10.42.0.1`
- Metadata host route via `10.42.0.2`
- Tenant gateway ICMP: passed
- Provider gateway `192.168.21.1` ICMP: passed
- Internet `1.1.1.1` ICMP: passed
- DNS through BIND at `192.168.21.10`: passed
- HTTP retrieval from `example.com`: passed

Validated from the provider network:

- ICMP to Floating IP `192.168.21.200`: passed with zero packet loss
- Connectivity remained operational after a rolling OVS restart.

Additional focused acceptance checks also passed:

- A second VM without a Floating IP reached `1.1.1.1` and `example.com` through router SNAT.
- The second VM retrieved OpenStack metadata from `169.254.169.254`.
- East-west ICMP between `10.42.0.128` and `10.42.0.144` passed.
- A deny security group blocked inbound Floating-IP ICMP; adding an ICMP rule enabled it immediately. The temporary second Floating IP was then released.
- A 1 GiB Cinder RBD volume attached as `/dev/vdb`, appeared in libvirt as `cinder.volumes/<volume-id>`, detached cleanly, and was deleted.
- Rebooting `poc-egress-vm` preserved its fixed IP, Floating IP, compute placement, and ACTIVE state. Transient ICMP loss during reboot was expected; post-reboot ICMP passed with zero loss.

A dedicated guest-filesystem test also passed: a 1 GiB Cinder RBD volume appeared as `/dev/vdb`, was formatted as ext4, mounted, written, unmounted, remounted, and both the original marker and a second file were read back successfully. The temporary VM, Floating IP, keypair, and volume used for this destructive filesystem test were removed afterward.

The named resources are intentionally retained for repeatable PoC regression tests.
