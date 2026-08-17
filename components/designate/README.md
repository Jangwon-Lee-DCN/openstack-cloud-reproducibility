# designate operational contract

This is the authoritative issue, remediation, reconciliation, and verification contract for `designate`.

## Known issues and scope

The upstream 2026.1.0 chart sources did not deploy successfully on this
cluster without local corrections:

- bootstrap Jobs used Helm post-install hooks while deployments depended on
  those Jobs, creating a circular wait;
- the Designate 2026.1 image lacked the chart's expected
  `/var/lib/openstack/bin/designate-api-wsgi` file;
- central did not mount `pools.yaml`;
- a service-cleaner volume name was inconsistent;
- control-plane tolerations and mDNS/worker host networking were absent;
- the legacy PowerDNS image and configuration were incompatible with the
  selected PowerDNS 4.9 runtime and schema;
- Cilium LoadBalancer SNAT changed the NOTIFY source, which PowerDNS strictly
  compares with the configured primary addresses.

## Remediation

The patched charts:

- render control-plane tolerations for all Designate services and PowerDNS;
- remove the circular bootstrap hook annotations;
- mount the pool configuration into central;
- embed a small WSGI entry point for the Designate API image;
- correct the service-cleaner volume reference;
- support host networking for mDNS and worker;
- run PowerDNS 4.9.16 unprivileged on port 5353;
- remove obsolete PowerDNS options and use current secondary-zone terminology;
- add Pod security context and replica anti-affinity support.

Site values register the stable per-node Cilium router addresses as mDNS
primaries and use `192.168.21.9:53` as the authoritative DNS target.

The Horizon image adds the official `designate-dashboard` 22.0.0 wheel above
the immutable image containing the existing Octavia and VPC panels. Its wheel
SHA-256 and final OCI image digest are pinned.

Patched packages are stored at:

- `helm/packages/patched/designate-2026.1.0.tgz`
- `helm/packages/patched/powerdns-2026.1.0.tgz`

The matching unmodified packages are retained under
`helm/packages/upstream/`.

## Reconciliation

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

## Verification

Run:

```bash
cd /home/ubuntu/openstack-cloud-services
./deployment/openstack-helm/scripts/verify-designate.sh
```

Acceptance requires:

1. two ready replicas for each core Designate service and PowerDNS;
2. successful zone and A-record creation through the OpenStack API;
3. both resources reaching `ACTIVE`;
4. `192.168.21.9` returning the created authoritative A record;
5. both BIND controllers resolving the delegated record to the same value.
6. an authenticated Horizon request to `/horizon/project/dnszones/` returning
   HTTP 200 while the Octavia and VPC Python plugins remain importable.

The accepted test record is:

```text
www.designate-poc.cloud.dcn.ssu.ac.kr. A 192.0.2.80
```
