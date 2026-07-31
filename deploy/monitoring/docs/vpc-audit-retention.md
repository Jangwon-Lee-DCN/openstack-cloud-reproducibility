# VPC drift and operator audit policy

The scheduled drift auditor is read-only. It runs once per project namespace with
that project's `openstack-credentials` Secret and a service account that can only
list the three audited CRDs. It never prints or exports credential data.

Automatic repair is deliberately disabled. After reviewing the JSON report, an
operator may request one controller retry with:

```sh
APPROVE_RECONCILE=yes scripts/request-drift-reconcile.sh NAMESPACE RESOURCE NAME
```

The unified audit API returns at most 2,000 entries. Security Group annotations
retain 50 changes per object and Elastic IP association history retains 10.
Kubernetes Event retention follows the API server policy. Long-term retention
belongs in the cluster log backend; the facade does not create a second identity
store.

Audit records use opaque Keystone user/project IDs and request IDs. They must not
contain tokens, passwords, application-credential secrets, `clouds.yaml`, or
request bodies. CSV exports inherit the caller's project scope and should be
handled as operationally sensitive data.
