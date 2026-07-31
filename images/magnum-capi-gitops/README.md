# Magnum CAPI GitOps runtime images

These Dockerfiles are the final build definitions used by
`openstack-cloud-services`.

Source is pinned by the `magnum-capi-gitops` repository commit:

```text
100ced2 verify live Magnum GitOps lifecycle
```

Build the Dockerfiles with that repository root as the build context.

Runtime pins:

```text
registry.dcn.ssu.ac.kr/openstack/magnum-capi-gitops@sha256:b2c36ac04d1891ff931a7c8a40660c2c3e8704d804cc6b986f8918e8c7e28ec2
registry.dcn.ssu.ac.kr/openstack/magnum-capi-repository-writer@sha256:f3fa6203204268c7bd9333a6c91308f50d6fe014dbd75d3eb43d95bc7b7dcc04
```

The source commit contains the full create, immutable update, rollback, and
delete verification record. No credentials or rendered cloud-credential
Secrets are stored here.
