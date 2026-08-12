# VPC drift and operator audit policy

The scheduled drift auditor is read-only. It runs once per project namespace with
that project's `openstack-credentials` Secret and a service account that can
only list the audited CRDs. It covers SG/rules, EIP, NAT/Internet router
gateways, Load Balancers, Endpoint Ports, Flow Logs, Private DNS zones/records,
ownership tags, and controller-shaped orphans. It never prints or exports
credential data.

Automatic repair is deliberately disabled. After reviewing the JSON report, an
operator may request one controller retry with:

```sh
APPROVE_RECONCILE=yes scripts/request-drift-reconcile.sh NAMESPACE RESOURCE NAME
```

Supported resources are `securitygroup`, `elasticip`, `natgateway`,
`internetgateway`, `loadbalancer`, `vpcendpoint`, `privatednszone`,
`flowlogconfig`, and `networkinterface`. This changes only a reconcile-request
annotation: the owning controller re-evaluates desired state and performs its
normal idempotent repair. The script never edits Neutron, OVN, Octavia, or
Designate directly and never removes a finalizer. Untracked resources reported
by the auditor remain a manual ownership/adoption decision.

The unified audit API returns at most 2,000 entries. Security Group annotations
retain 50 changes per object and Elastic IP association history retains 10.
Kubernetes Event retention follows the API server policy. Long-term retention
belongs in the cluster log backend; the facade does not create a second identity
store.

Audit records use opaque Keystone user/project IDs and request IDs. They must not
contain tokens, passwords, application-credential secrets, `clouds.yaml`, or
request bodies. CSV exports inherit the caller's project scope and should be
handled as operationally sensitive data.
