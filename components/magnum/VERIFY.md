# VERIFY

Run:

```bash
deploy/scripts/verify-magnum.sh
```

It verifies two ready API replicas, two ready conductor replicas, PDBs, the
`k8s_capi_helm_v1` driver, management-cluster Helm access, Gateway route
acceptance, and an authentication-enforced HTTP 401 from the internal API.

An authenticated `openstack coe cluster template list` must also complete.
End-to-end workload-cluster creation is a separate acceptance gate requiring
a supported Kubernetes image, flavors, tenant network, quotas, and Octavia.
