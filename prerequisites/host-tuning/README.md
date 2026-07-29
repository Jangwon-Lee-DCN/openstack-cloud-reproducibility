# Kubernetes host tuning

Run the installer on every Kubernetes node:

```bash
./install.sh
```

It installs:

- `99-kubernetes-inotify.conf`: raises conservative host-wide inotify ceilings
  needed by a dense Kubernetes control plane.
- `70-openstack-kvm.rules`: keeps `/dev/kvm` usable by QEMU after host reboots.
  The OpenStack-Helm libvirt container and the Ubuntu host may assign different
  numeric GIDs to their respective `kvm` groups, so group-only access is not
  portable across this deployment.

The KVM rule is intended only for dedicated, trusted compute hosts. Do not use
it on a multi-user host where local users must be prevented from accessing
hardware virtualization.
