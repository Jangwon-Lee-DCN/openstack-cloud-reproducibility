# Ironic Conductor Chart Fix

## ISSUE

Ironic Conductor could not initialize reliably with the unmodified 2026.1.0
chart. A generated RabbitMQ credential containing a URI-reserved slash failed
during the oslo.messaging/Kombu handoff. Once that credential was rotated,
the chart also failed to create the configured temporary and HTTP boot
directories in the volume used by the main container.

Kubernetes did not detect either condition because the upstream Conductor
container had no readiness probe.

## FIX

The frozen deployment uses a URI-safe, 64-character alphanumeric RabbitMQ
password stored only in:

- `deploy/secrets/ironic.values.sops.yaml`; and
- `deploy/releases/ironic.values.sops.yaml`.

The chart contains two explicit local patches:

- `templates/statefulset-conductor.yaml` mounts `ironic.conf` and `pod-data`
  into the init container, and adds an AMQP-connection readiness probe.
- `templates/bin/_ironic-conductor-init.sh.tpl` creates both
  `DEFAULT.tempdir` and `deploy.http_root` in the shared volume.

## RECONCILE

Deploy this repository's pinned `helm/openstack-helm/ironic` chart with the
site and SOPS values. Do not replace it with an unpatched upstream package,
and do not update only the live Kubernetes Secret.

## VERIFY

The accepted live state is:

- StatefulSet replicas/ready replicas: `2/2`;
- one Conductor on each controller node;
- `DEFAULT.tempdir` exists with mode `1777`;
- `deploy.http_root` exists after a fresh Pod recreation;
- each Conductor is Ready only after establishing AMQP;
- no `ValueError`, `PathNotFound`, or `DriverLoadError` appears after startup;
  and
- at least two running RabbitMQ connections exist for the Ironic user.

The 2026-07-30 deployment passed these checks with Helm revision 7.
