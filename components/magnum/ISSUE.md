# ISSUE

The upstream OpenStack-Helm 2026.1.0 Magnum chart and Airship Noble image
cannot directly run the selected CAPI Helm driver:

- the image has only the legacy Heat driver and no Helm client;
- the CAPI driver expects a static kubeconfig token;
- CAPO and workload CCM require different catalog regions but must emit the
  same canonical Nova provider ID;
- the upstream driver forces an API load balancer and cannot exercise the
  explicitly experimental direct-floating-IP comparison;
- the Airship image lacks the chart's `magnum-api-wsgi` path;
- the chart's filter-style healthcheck is incompatible with the image's
  `oslo.middleware`;
- private-registry pulls, control-plane taints, and two-node HA require
  additional chart settings.
- OpenStack CCM did not tolerate the initial `NotReady` taint, creating a
  bootstrap ordering deadlock.
- Legacy clusters pinned `openstack/RegionOne` in immutable infrastructure
  identities. Reusing that cloud entry for `RegionOne-VM` prevented CAPO from
  deleting old Machines during an in-place chart migration.
- The internal repository index still advertised the retired
  `magnum-workload-chart-repository.capi-system` URL even though Magnum used
  the HA `magnum-chart-repository.openstack` service.
- The project default quota of 10 security groups was exhausted by two
  clusters and their Kubernetes LoadBalancer Services.
- A direct ORC v2.6 upgrade reset the HA overlay and left one controller
  replica.
- Magnum cleanup uses a label-selected Kubernetes Secret collection delete.
  Granting only the singular `delete` verb caused a hidden 403 and left
  clusters in `DELETE_IN_PROGRESS` after all CAPI/cloud resources were gone.
