# RECONCILE

1. Verify the upstream source archive checksum.
2. Apply `port-list-limit.patch` to CAPO `v0.14.6`.
3. Build the controller using the pinned upstream Dockerfile and push it to
   Harbor.
4. Pin the resulting digest in the management-cluster kustomization.
5. Copy the existing Harbor pull secret into `capo-system`; never copy its
   plaintext value into Git.
6. Reconcile both CAPO replicas and retain required cross-node anti-affinity.
