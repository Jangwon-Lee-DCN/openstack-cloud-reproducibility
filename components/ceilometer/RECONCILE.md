# RECONCILE: Ceilometer

1. Build or pull the digest-pinned libvirt overlay image.
2. Generate target-cloud AMQP URLs using port 5672, then SOPS-encrypt the
   values profile.
3. Run `deploy/scripts/reconcile.sh`; it removes the immutable DB-sync Job,
   upgrades the upstream chart with site values, and applies external PDBs.
4. Confirm the compute DaemonSet runs only on `openstack-compute-node=enabled`
   nodes.

No tenant guest agent is installed by this procedure.
