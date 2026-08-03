# Service-to-Service Regression

Run this gate after IAM, Keystone policy, service credential, or endpoint
changes:

```bash
cd /home/ubuntu/openstack-cloud-reproducibility
./deploy/scripts/verify-service-to-service.sh
./deploy/scripts/verify-magnum.sh
./deploy/scripts/verify-full-stack.sh
```

The first script creates disposable resources and verifies these real call
chains:

| Test | Required service path |
| --- | --- |
| Tenant network, subnet, and router | Keystone to Neutron |
| Active Cirros server and bound port | Nova to Glance and Neutron |
| Attached RBD-backed volume | Nova to Cinder |
| Active secret | Keystone to Barbican |
| Active DNS zone | Designate to PowerDNS |
| Active/standby Amphora load balancer | Octavia to Glance, Nova, and Neutron |

All names use an `s2s-<timestamp>` prefix and a trap removes the load balancer,
server, volume, DNS zone, secret, router, subnet, and network. The client image
does not provide `openstack server wait`; the verifier intentionally polls
resource fields through normal API calls instead.

Magnum uses the deployed CAPI driver. It therefore does not exercise a legacy
Magnum-to-Heat path. `verify-magnum.sh` validates Magnum API/conductor HA, the
CAPI driver entry point, management-cluster access, and internal API routing.
CAPO performs the eventual Nova and Neutron calls for workload clusters; the
disposable Nova/Neutron tests above protect those service credentials, while a
full workload-cluster creation remains a separate, higher-cost acceptance
test.

## 2026-08-02 result

All disposable service paths passed. The full-stack gate initially found one
stale, non-ready `heat-cfn` Pod and one stale, non-ready `placement-api` Pod
left by the earlier host interruption. Recreating only those two Pods restored
both HA Deployments to 2/2, after which the full-stack gate passed. No
`s2s-*` OpenStack resources remained.
