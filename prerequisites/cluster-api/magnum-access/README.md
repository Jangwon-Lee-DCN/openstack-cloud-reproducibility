# Magnum Access to the Management Cluster

Magnum runs in the same Kubernetes cluster as CAPI/CAPO. Its conductor uses its
projected ServiceAccount token through kubeconfig `tokenFile`; no cluster-admin
certificate, static token or private key is embedded in Helm values.

The `magnum-capi-manager` role is limited to dynamic Namespace lifecycle,
namespaced Helm resources and CAPI-related API groups. Kubernetes RBAC cannot
restrict Namespace names by prefix, so admission policy for the `magnum-*`
prefix remains a production hardening item.

The local OpenStack-Helm Magnum chart adds `tokenFile` and
`certificateAuthorityFile` kubeconfig support. The patch must be retained in
the reproducibility repository.
