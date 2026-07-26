# Full-Stack Reconciliation

`openstack-cloud-reproducibility` is the immutable artifact source for the
accepted PoC deployment. `openstack-cloud-services` is the consumer and must
not maintain an independent chart fork.

## Locked inputs

- `release-lock.yaml`: all 19 installed Helm releases, exact package path,
  SHA-256, chart/app versions, and encrypted final values snapshot
- `helm/packages/upstream`: unmodified packages
- `helm/packages/patched`: Ironic, Nova, and OVN packages used by the cluster
- `deploy/releases`: SOPS-encrypted snapshots from `helm get values`
- `deploy/values/site`: human-maintained non-secret layers
- `deploy/secrets`: human-maintained SOPS profiles
- `images` and `deploy/manifests`: custom telemetry artifacts

## Usage

```bash
cd /home/ubuntu/openstack-cloud-reproducibility
./deploy/scripts/verify-full-stack.sh
./deploy/scripts/reconcile-full-stack.sh
```

Set `BUILD_IMAGES=1` only when the locked custom images are unavailable. A
rebuilt digest must match the recorded digest or be reviewed and committed.

## Environment boundary

The release snapshots reproduce the current PoC, including environment-specific
credentials and endpoints, and therefore remain SOPS-encrypted. A new cloud
must create a new encrypted profile rather than reusing identities blindly.
The chart packages and fixes remain identical across profiles.

Helm hooks in these charts can deadlock with Helm `--wait`. The script installs
without `--wait`, then waits for hook Jobs and workloads explicitly.
