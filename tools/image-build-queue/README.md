# DCN image build queue

This directory integrates the maintained Pueue command queue with the existing
OpenStack image build script. It deliberately remains a small host service: no
Kubernetes controller, CRD, database, or web API is introduced.

## Contract

- Pueue `v4.0.4` client and daemon binaries are downloaded from the upstream
  release and verified against the committed SHA-256 values.
- One persistent systemd service runs as the existing `ubuntu` operator.
- Pueue groups have parallelism one. Horizon, Nova, Neutron, Keystone,
  Octavia, Magnum, and other platform images have independent groups.
- Requests accept only allow-listed components and exact Git commits that are
  present on an `origin/*` branch.
- The request fingerprint includes every source repository and revision.
  Duplicate queued, running, or successful requests reuse the same task.
- The queue result is an immutable registry reference containing a digest.
  A failed build never returns a digest.
- Building does not update a Helm value, release lock, Deployment, or running
  Pod. Promotion remains a separately reviewed workflow.
- The client passes an allow-listed environment to Pueue because Pueue stores
  task environments in its persistent state. Session tokens and SOPS
  variables must never be captured.

When the service is active, `deploy/scripts/build-images.sh` rejects direct
invocation. A fresh rebuild host without the queue can still bootstrap images.
Routine work must not stop the service to bypass serialization.

## Install

Installation is owned by production automation. The underlying operation is:

```bash
sudo tools/image-build-queue/install.sh
```

The installer creates:

```text
/usr/local/bin/dcn-image-build
/usr/local/libexec/dcn-image-build-queue/
/etc/dcn-image-build-queue/pueue.yml
/var/lib/dcn-image-build-queue/
/run/dcn-image-build-queue/
/etc/systemd/system/dcn-image-build-queue.service
```

## Submit Horizon

Every source must be explicit. Paths identify local Git repositories; the
optional `@REVISION` defaults to their current `HEAD`, but the resolved commit
must already exist on an `origin/*` branch.

```bash
dcn-image-build submit --component horizon-complete \
  --source reproducibility=/path/to/openstack-cloud-reproducibility@FULL_SHA \
  --source vpc_dashboard=/path/to/openstack-vpc-dashboard@FULL_SHA \
  --source telemetry_dashboard=/path/to/openstack-telemetry-dashboard@FULL_SHA \
  --source s3_dashboard=/path/to/openstack-s3-dashboard@FULL_SHA \
  --wait
```

The first JSON line records the request/task identity. On success, `--wait`
prints the immutable image reference on the final line.

## Operate

```bash
dcn-image-build health
dcn-image-build list
dcn-image-build status REQUEST_OR_TASK_ID
dcn-image-build wait REQUEST_OR_TASK_ID
dcn-image-build log REQUEST_OR_TASK_ID
dcn-image-build cancel REQUEST_OR_TASK_ID
systemctl status dcn-image-build-queue.service
```

Do not call the bundled Pueue client directly for routine builds. The wrapper
provides source validation, environment scrubbing, deduplication, and digest
validation that raw Pueue does not.

## Validation

```bash
python3 -m unittest discover -s tools/image-build-queue/tests -p 'test_*.py' -v
python3 tools/image-build-queue/tests/integration.py
bash -n tools/image-build-queue/install.sh tools/image-build-queue/init-groups
```

The integration test runs the checksum-pinned upstream daemon with isolated
temporary state and verifies FIFO, deduplication, environment scrubbing, and
restart recovery without building or applying a production image.
