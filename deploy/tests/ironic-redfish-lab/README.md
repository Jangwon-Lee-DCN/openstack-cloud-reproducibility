# Ironic virtual Redfish deployment lab

This PoC validates the complete Ironic direct-deploy path without physical
bare-metal hardware. A libvirt VM is exposed as a Redfish system by
`sushy-tools`, boots the official Ironic Python Agent (IPA) through Redfish
virtual media, receives a whole-disk CirrOS image, and reboots from its local
disk.

## Scope and safety

- The VM runs in the `ubuntu` user's `qemu:///session` libvirt instance and
  remains separate from Nova's system libvirt.
- `br-ironic-poc` is an isolated host-only bridge. It does not modify `eno1`,
  `eno2`, or `br-ex`, and it does not run DHCP on the management LAN.
- The host runs DHCP only on `br-ironic-poc`; the fixed lab address is
  `172.31.250.100`.
- The emulator listens on `192.168.21.10:8000`, and the artifact service
  listens on `192.168.21.10:8001`.
- The emulator has no production-grade authentication or TLS. It must manage
  test VMs only.

## Validated resources

| Resource | Value |
| --- | --- |
| Ironic node UUID | `7dcbbfec-f38e-4536-b917-2e208a95f647` |
| Libvirt domain | `ironic-redfish-node-0` |
| Libvirt domain UUID | `228c6414-fd3e-4f62-a7a5-bb5aadb18f77` |
| vCPU / RAM / disk | 2 / 2 GiB / 10 GiB qcow2 |
| MAC / IPA address | `52:54:00:10:00:01` / `172.31.250.100` |
| Redfish endpoint | `http://192.168.21.10:8000` |
| Artifact endpoint | `http://192.168.21.10:8001` |

Pinned artifacts and their verified SHA-256 values:

| Artifact | SHA-256 |
| --- | --- |
| `ipa.kernel` | `2302f2cb75b3ed35c55bf75d062a17fc4e88199c0bc00bce4d2dc3be90311d6a` |
| `ipa.initramfs` | `ecccc8f6b747a385024765151e22fd442a481cbde320fc06d07ee4b0a9f0d5a6` |
| CirrOS 0.6.3 x86-64 disk | `7d6355852aeb6dbcd191bcda7cd74f1536cfe5cbf8a10495a7283a8396e4b75b` |

## ISSUE

The end-to-end test exposed four independent packaging and networking
problems:

1. The Airship Ironic 2026.1 image contains neither `mkisofs` nor a compatible
   ISO authoring tool. Redfish virtual-media deployment first failed while
   creating its boot ISO.
2. Ironic initially built temporary ISO files on a different filesystem from
   `master_iso_images`, causing an `EXDEV` hard-link failure.
3. `[pxe]` kernel parameters do not apply to Redfish virtual media. Without a
   separate `[redfish] kernel_append_params`, IPA rejected the self-signed
   internal Gateway certificate.
4. QEMU user-mode networking assigned `10.0.2.15`, which accepted outbound
   traffic but was unreachable from an Ironic conductor. After moving to the
   routed PoC bridge, BIND initially returned `REFUSED` because the new subnet
   was not in `internal-networks`.

## FIX

- `install-boot-tools.sh` pins `genisoimage`, `libmagic`, the magic database,
  `isolinux.bin`, and `ldlinux.c32` below
  `/var/lib/ironic/boot-tools` on both controllers.
  The Ubuntu packages are pinned to `genisoimage=9:1.1.11-3.5`,
  `libmagic1t64=1:5.45-3build1`, and the
  `3:6.04~git20190206.bf6db5b4+dfsg1-3ubuntu3` isolinux/syslinux build; the
  script rejects unexpected artifact hashes.
- The pinned Ironic chart prepends that directory to `PATH` and defines
  `LD_LIBRARY_PATH` and `MAGIC`. `DEFAULT.tempdir` stays under
  `/var/lib/ironic` so virtual-media hard links remain on one filesystem.
- The site values define `[redfish] kernel_append_params` separately. The
  `ipa-insecure=1` exception is PoC-only and must be removed once IPA trusts the
  institutional CA.
- `ironic-lab-network.service` creates `br-ironic-poc` and `tap-ironic0`.
  `ironic-lab-dnsmasq.service` provides DHCP without binding a DNS port.
  Controller-1 receives a persistent route through `192.168.21.10`.
- Both BIND replicas permit `172.31.250.0/24` in `internal-networks`.

## RECONCILE

Install the conductor boot tools:

```bash
sudo ./install-boot-tools.sh cloud-controller-1
```

On controller-0, install and start the isolated network units:

```bash
sudo install -d -m 0755 /usr/local/libexec/ironic-lab
sudo install -m 0755 setup-network.sh \
  /usr/local/libexec/ironic-lab/setup-network.sh
sudo install -m 0644 ironic-lab-network.service \
  ironic-lab-dnsmasq.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ironic-lab-network.service \
  ironic-lab-dnsmasq.service
```

Install `ironic-lab-route.service` on controller-1. The VM's persistent NIC is
defined by `tap-interface.xml`. Runtime images, emulator configuration, and
artifacts live under `/home/ubuntu/ironic-redfish-lab`.

Ironic CLI operations require a system-scoped token:

```bash
unset OS_PROJECT_NAME OS_PROJECT_ID
export OS_SYSTEM_SCOPE=all
```

The node uses `redfish-virtual-media`, `direct`, and `noop` for the boot,
deploy, and network interfaces respectively. Automated cleaning is disabled
for this isolated PoC.

## VERIFY

The complete path was verified on 2026-07-30:

- both conductors executed the pinned `mkisofs` compatibility binary;
- Redfish power control and inspection reported 2 CPUs, 2048 MiB RAM, and a
  9 GiB usable local disk;
- the generated ISO contained the official IPA kernel and initramfs plus the
  Redfish-specific callback parameters;
- IPA received `172.31.250.100`, resolved
  `api.internal.cloud.dcn.ssu.ac.kr`, and heartbeated through the internal
  Gateway;
- controller-1 reached the IPA API across the persistent routed subnet;
- Ironic completed `write_image`, ejected virtual media, booted only `vda`,
  and reached `provision_state=active` with `last_error=null`;
- the serial console showed the deployed CirrOS kernel booting from the 10 GiB
  local disk.

Run `verify.sh` for the non-destructive Redfish and Ironic checks. An explicit
deploy/undeploy test remains destructive to the VM disk and is intentionally
not part of that default script.

## Production transition

This routed single-VM bridge is a lab substitute, not the production
provisioning design. Physical nodes require a dedicated provisioning VLAN,
redundant L3 reachability from every conductor, production DHCP/PXE or
virtual-media policy, institutional CA trust in IPA, cleaning networks, and
multiple real BMCs. Remove all `ipa-insecure` settings before production.
