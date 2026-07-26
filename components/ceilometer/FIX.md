# FIX: Libvirt Overlay, Correct AMQP, and Provider-Only Collection

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
