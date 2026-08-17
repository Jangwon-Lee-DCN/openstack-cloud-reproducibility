# ceilometer operational contract

This is the authoritative issue, remediation, reconciliation, and verification contract for `ceilometer`.

## Known issues and scope

## Affected baseline

- OpenStack-Helm chart `2026.1.0`
- Ceilometer `26.0.0`
- Upstream Airship image pinned in `images/ceilometer/upstream/BASELINE.md`

## Symptoms

- The compute pollster raised `ImportError: python-libvirt module is missing`.
- Notification workers repeatedly lost RabbitMQ connections.
- An initial generated transport configuration used port 15672, the RabbitMQ
  management HTTP API, instead of AMQP port 5672.
- Enabling every central pollster produced expected errors for services not
  installed in the PoC.

## Root cause

The image omitted Python libvirt bindings. The generated multi-bus URLs chose
the wrong endpoint port. The default broad pollster set assumes optional
OpenStack services that are absent here.

## Remediation

- Extend the immutable upstream image with Ubuntu `python3-libvirt` and copy
  the bindings into the OpenStack virtual environment.
- Pin the built image digest in `deploy/values/ceilometer.yaml`.
- Use AMQP port 5672 for Nova, Cinder, Glance, Keystone, Neutron, and Heat
  notification buses.
- Exclude unsupported perf/rate meters and pollsters for optional services.
- Use libvirt metadata discovery with `fetch_extra_metadata=false` to minimize
  tenant metadata collection.
- Run central and notification workers as two hard-anti-affinity replicas and
  add explicit PodDisruptionBudgets.

Known limitation: libvirt access and periodic polling are confirmed, but an
actual measure has not yet appeared in the Gnocchi index. This component must
not be declared production-ready until VERIFY passes end to end.

## Reconciliation

1. Build or pull the digest-pinned libvirt overlay image.
2. Generate target-cloud AMQP URLs using port 5672, then SOPS-encrypt the
   values profile.
3. Run `deploy/scripts/reconcile.sh`; it removes the immutable DB-sync Job,
   upgrades the upstream chart with site values, and applies external PDBs.
4. Confirm the compute DaemonSet runs only on `openstack-compute-node=enabled`
   nodes.

No tenant guest agent is installed by this procedure.

## Verification

- Two central and two notification workers are Ready on distinct controllers.
- One compute pollster is Ready per compute-labeled node.
- Importing `libvirt` succeeds and active libvirt domains are visible.
- Notification logs contain neither recurring connection closure errors nor
  management-port URLs.
- A known VM produces a provider-side CPU or disk sample in Gnocchi.

The final end-to-end sample condition is currently pending and blocks a
production-ready declaration.
