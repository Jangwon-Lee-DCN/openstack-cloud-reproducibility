# RECONCILE: Octavia

1. Ensure `/var/lib/octavia/run` exists on every controller with numeric
   owner/group `42424`, mode `0750`.
2. Discover the current `ovn-ovsdb-nb` and `ovn-ovsdb-sb` EndpointSlice
   addresses. Never copy stale Pod IPs from an earlier cluster.
3. Update `deploy/values/site/octavia.yaml` with all discovered remotes.
4. Install and verify `prerequisites/octavia-jobboard` before enabling
   `jobboard_enabled`. Confirm Sentinel reports a reachable quorum and all
   three Ceph-backed Pods are Ready.
5. Apply `deploy/secrets/octavia-amphora-certs.secret.sops.yaml` by streaming
   SOPS output directly to `kubectl`; never persist its private keys.
6. Copy only `ca.crt` from the internal Gateway CA Secret into the `openstack`
   namespace. The wrapper performs this without exporting any CA private key.
7. Run `deploy/scripts/reconcile-octavia-amphora-resources.sh` to reconcile the
   management network, node ports, security group, flavor, keypair, and image
   tag. Replace the test-only image with a site-built image for production.
8. Decrypt `deploy/secrets/octavia.values.sops.yaml` only to a mode-`0600`
   temporary file and destroy it after Helm exits.
9. Upgrade the frozen patched Octavia chart with `--no-hooks` for ordinary
   reconciliation. Run the initial chart hooks when databases, Keystone
   service records, or RabbitMQ users do not yet exist.
10. Wait for two API, two driver-agent, two housekeeping, two worker, and two
   health-manager instances, split across the controllers.
11. Confirm both controller hostPaths contain `status.sock`, `get.sock`, and
   `stats.sock`.
12. Run the checks in `VERIFY.md`.
