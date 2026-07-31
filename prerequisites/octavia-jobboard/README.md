# Octavia Taskflow Jobboard

This prerequisite deploys a dedicated Valkey replication group with Sentinel
for Octavia Taskflow. It must not share the Redis instances used by Harbor,
Gitea, or Argo CD.

## Frozen inputs

- Bitnami Valkey Helm chart: `6.2.4`
- Valkey and Sentinel images are pinned by digest in `values/valkey.yaml`.
- Persistent data uses three 2 GiB `rook-ceph-block` volumes.
- Authentication is stored only in
  `secrets/octavia-valkey-auth.secret.sops.yaml`.

The release name is `octavia-valkey`, but `fullnameOverride: valkey` preserves
the service name expected by the OpenStack-Helm Octavia chart:
`valkey.openstack.svc.cluster.local:26379`.

## Install

```bash
scripts/install.sh
```

## HA boundary

One primary and two replicas run with a Sentinel sidecar in every Pod. They are
spread across the two current controllers as evenly as Kubernetes permits.
This supports Octavia worker process failure and many individual Pod failures.

It cannot guarantee Sentinel majority after the loss of either physical node:
three voting members cannot be distributed across only two failure domains so
that either domain retains a majority. A third controller or dedicated storage
node is required for true quorum HA. Production must place one voting member
in each of at least three independent failure domains.

## Security

Valkey data endpoints use the generated credential. Sentinel discovery is
cluster-internal and unauthenticated because Octavia 2026.1/Taskflow does not
send the data-store credential when it discovers a Sentinel master. Do not
print the Valkey credential, pass it on a command line outside the verification
script, or commit a decrypted Secret. Ceph snapshots and backups containing
Valkey AOF data must be protected as sensitive infrastructure data.
