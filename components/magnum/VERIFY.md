# VERIFY

Run:

```bash
deploy/scripts/verify-magnum.sh
```

It verifies two ready API replicas, two ready conductor replicas, PDBs, the
`k8s_capi_helm_v1` driver, management-cluster Helm access, Gateway route
acceptance, and an authentication-enforced HTTP 401 from the internal API.

An authenticated `openstack coe cluster template list` must also complete.

The workload acceptance gate creates two minimal clusters:

- one control-plane and one worker behind an OVN Octavia API load balancer;
- one control-plane and one worker with a floating IP directly attached to the
  control-plane port.

For each cluster, verify two Ready nodes, all baseline Helm releases, DNS,
ClusterIP traffic, and Internet egress. The LB must be ACTIVE/ONLINE with a
TCP 6443 member. The no-LB cluster must have no matching Octavia load balancer.
