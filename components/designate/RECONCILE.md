# RECONCILE: Designate

Use the service repository as the environment-specific orchestrator:

```bash
cd /home/ubuntu/openstack-cloud-services
./deployment/openstack-helm/scripts/install-designate.sh
```

The process deploys the locally pinned charts, applies the conditional
PowerDNS 4.9 database migration, reconciles the Designate pool, restarts
workers to invalidate cached pool data, applies the authoritative DNS VIP,
and applies the public Gateway route.

After a Cilium rebuild, inspect `cilium_host` on both controllers. If either
address changed, update the Designate pool values and rerun reconciliation.
BIND parent delegation and the child-zone forward rule are maintained under
`deployment/bind-haproxy-keepalived/`.
