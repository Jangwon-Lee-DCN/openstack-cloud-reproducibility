# Full-Stack Reconciliation

`openstack-cloud-reproducibility` is the immutable artifact source for the
accepted PoC deployment. `openstack-cloud-services` is the consumer and must
not maintain an independent chart fork.

## Locked inputs

- `release-lock.yaml`: all 20 installed Helm releases, exact package path,
  SHA-256, chart/app versions, and encrypted final values snapshot
- `helm/packages/upstream`: unmodified packages
- `helm/packages/patched`: Ironic, Nova, OVN, Skyline, and Horizon packages used by the cluster
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

Set `BUILD_IMAGES=1` for an empty Harbor. The source build now covers every
private runtime image family, builds Magnum before its GitOps derivative, and
builds Horizon once from a public digest-pinned base instead of relying on a
chain of private parent images. It writes immutable results to
`deploy/generated/rebuilt-images.env`. Review those references and promote
them with `deploy/scripts/apply-rebuilt-image-lock.py` before reconciling
workloads; a new digest must
never be hidden behind an old tag or silently substituted.

The build requires clean, commit-pinned checkouts of `openstack-vpc-dashboard`,
`vpc-control-plane`, and `magnum-capi-gitops` beside this repository. It stops
instead of packaging uncommitted source. `verify-image-rebuild-closure.py`
guards the required image families, public bootstrap boundary, pinned parent
images, and the cumulative Octavia, Designate, VPC, project self-service, and
Magnum UI Horizon extensions.

## Environment boundary

The release snapshots reproduce the current PoC, including environment-specific
credentials and endpoints, and therefore remain SOPS-encrypted. A new cloud
must create a new encrypted profile rather than reusing identities blindly.
The chart packages and fixes remain identical across profiles.

Helm hooks in these charts can deadlock with Helm `--wait`. The script installs
without `--wait`, then waits for hook Jobs and workloads explicitly.

Skyline is reconciled after Horizon. The final HTTPRoute assigns `/` to
Skyline and `/horizon/` to Horizon. Both dashboards run two replicas spread
across the controllers; component-specific compatibility details are recorded
under `components/skyline/`.
