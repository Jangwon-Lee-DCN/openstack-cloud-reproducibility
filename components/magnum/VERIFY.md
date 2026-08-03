# VERIFY

Run:

```bash
deploy/scripts/verify-magnum.sh
```

It verifies two ready API replicas, two ready conductor replicas, PDBs, both
the `k8s_capi_helm_v1` and `k8s_capi_gitops_v1` drivers, management-cluster Helm access, Gateway route
acceptance, and an authentication-enforced HTTP 401 from the internal API.

The Phase 50 GitOps reconciler additionally verifies Argo CD, Porch repository
sync, the deployment ApplicationSet, and two ready repository-writer replicas.

An authenticated `openstack coe cluster template list` must also complete.

The workload acceptance gate creates two minimal clusters:

- one control-plane and one worker behind an OVN Octavia API load balancer;
- one control-plane and one worker with a floating IP directly attached to the
  control-plane port.

For each cluster, verify two Ready nodes, all baseline Helm releases, DNS,
ClusterIP traffic, and Internet egress. The LB must be ACTIVE/ONLINE with a
TCP 6443 member. The no-LB cluster must have no matching Octavia load balancer.

The extended gate also verifies:

- Cinder CSI data survives a Pod restart and a worker Machine replacement;
- a Kubernetes LoadBalancer Service receives a floating IP and returns HTTP
  200 through an ACTIVE/ONLINE OVN Octavia pool member;
- create, delete, exact cloud-resource leak audit, and same-name recreation;
- controller-0 loss of CAPI, CAPO, ORC, Magnum API, and Magnum conductor Pods
  leaves controller-1 able to serve Magnum and reconcile workload clusters.

This Pod-level management failover does not prove physical-node HA. A
two-member management etcd cluster loses quorum when either host is lost; use
at least three management etcd members before claiming host-failure tolerance.

The live acceptance run passed all of the extended gates above. The lifecycle
test also proved that the corrected `deletecollection` RBAC removes the Magnum
record, generated Secrets, and application credential after CAPI finishes
cloud-resource deletion, and that the same Magnum cluster name can be reused.
