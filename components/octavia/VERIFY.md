# VERIFY: Octavia

## Control plane

```bash
helm -n openstack status octavia
kubectl -n openstack get pods -l application=octavia -o wide
kubectl -n openstack get deploy \
  octavia-api octavia-driver-agent octavia-housekeeping
```

Expected: two ready replicas for each deployment, split across the two
controllers.

## API and dashboards

```bash
curl -ksS -o /dev/null -w '%{http_code}\n' \
  https://cloud.dcn.ssu.ac.kr/load-balancer/v2/lbaas/providers
kubectl -n openstack exec deploy/horizon -- \
  python3 -c 'import octavia_dashboard; print(octavia_dashboard.__file__)'
```

The unauthenticated API response must be `401`. An authenticated provider query
must contain `ovn`. Skyline runtime configuration must map both the service and
extension named `load-balancer` to `octavia`.

## Data plane

Run `deploy/scripts/verify-octavia-e2e.py` from a client container populated
with the standard Keystone `OS_*` variables. Acceptance requires:

- load balancer, listener, pool, and members remain `ACTIVE`;
- the load balancer remains `ONLINE`;
- provider is `ovn`;
- repeated HTTP requests to the LB Floating IP return responses from both
  backend names.
