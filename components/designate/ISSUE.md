# ISSUE: OpenStack-Helm Designate and PowerDNS Compatibility

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
