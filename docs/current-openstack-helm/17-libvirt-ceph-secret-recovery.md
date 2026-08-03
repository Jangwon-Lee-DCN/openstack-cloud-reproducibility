# Libvirt Ceph secret recovery

## ISSUE

Nova uses a fixed libvirt secret UUID to authenticate QEMU to the Ceph RBD
pools. A host reboot can restart libvirtd while Kubernetes retains the existing
Pod object. Init containers therefore do not necessarily rerun. If libvirt's
secret state is absent, the Pods still appear healthy because the upstream
probe checks only `virsh connect`; every new RBD-backed VM then fails with
`Secret not found`.

## FIX

The pinned OpenStack-Helm libvirt chart is patched in
`helm/openstack-helm/libvirt/templates/bin/_libvirt.sh.tpl`.

- The main libvirt container checks the configured Ceph secret UUID every 30
  seconds.
- A missing secret is redefined from the already-mounted Ceph keyring without
  restarting libvirt or deleting the Pod.
- The secret value is applied while shell tracing is disabled, preventing the
  Ceph key from appearing in container logs.
- Both the primary and optional external-Ceph secret are supported.

## RECONCILE

Deploy the pinned local chart while retaining the release values:

```bash
helm upgrade libvirt helm/openstack-helm/libvirt \
  --namespace openstack --reuse-values --wait --timeout 5m
kubectl -n openstack rollout status daemonset/libvirt-libvirt-default \
  --timeout=180s
```

Fresh-server automation installs
`helm/packages/patched/libvirt-2026.1.0-dcn1.tgz` through `release-lock.yaml`.
The original upstream package remains unchanged under `helm/packages/upstream`.
The lock checksum and `helm/packages/patched/SHA256SUMS` must both match before
reconciliation; do not fetch an unpatched public libvirt package.

## VERIFY

Non-mutating presence check:

```bash
bash deploy/scripts/verify-libvirt-ceph-secret-recovery.sh
```

Controlled self-healing exercise:

```bash
bash deploy/scripts/verify-libvirt-ceph-secret-recovery.sh --exercise-repair
```

The exercise deliberately undefines only the configured libvirt secret and
waits up to 120 seconds for restoration. Follow it with the disposable service
matrix to prove actual QEMU/RBD use:

```bash
bash deploy/scripts/verify-service-to-service.sh
```

The expected chain is Nova VM `ACTIVE`, Neutron Port `ACTIVE`, Cinder RBD
volume `in-use`, and successful cleanup. The extended matrix also verifies
Barbican, Designate, and Amphora Octavia dependencies.
