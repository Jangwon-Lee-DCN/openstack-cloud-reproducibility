# RECONCILE: Octavia

1. Ensure `/var/lib/octavia/run` exists on every controller with numeric
   owner/group `42424`, mode `0750`.
2. Discover the current `ovn-ovsdb-nb` and `ovn-ovsdb-sb` EndpointSlice
   addresses. Never copy stale Pod IPs from an earlier cluster.
3. Update `deploy/values/site/octavia.yaml` with all discovered remotes.
4. Decrypt `deploy/secrets/octavia.values.sops.yaml` only to a mode-`0600`
   temporary file and destroy it after Helm exits.
5. Upgrade the frozen patched Octavia chart with `--no-hooks` for ordinary
   reconciliation. Run the initial chart hooks when databases, Keystone
   service records, or RabbitMQ users do not yet exist.
6. Wait for two API, two driver-agent, and two housekeeping replicas, one of
   each per controller.
7. Confirm both controller hostPaths contain `status.sock`, `get.sock`, and
   `stats.sock`.
8. Run the checks in `VERIFY.md`.
