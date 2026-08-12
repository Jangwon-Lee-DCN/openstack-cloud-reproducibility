# Deployment Inputs

This directory is the local correction layer over the clean charts under
`helm/openstack-helm`.

- `values`: non-secret OpenStack-Helm overrides
- `secrets`: SOPS-encrypted Helm values and Kubernetes Secrets
- `manifests`: custom image builders and resources not safely supplied by the
  upstream charts
- `scripts`: idempotent reconciliation and verification commands

Do not hand-edit live resources without translating the change back into this
directory and recording it in the component ISSUE/FIX documents.

The optional trusted VPC instance-identity path is installed only through
`scripts/install-vpc-instance-identity.sh`. It deploys the digest-pinned
metadata attestor before switching the OVN metadata agent. Once present,
`reconcile-full-stack.sh` automatically retains
`values/features/neutron-vpc-identity.yaml` on later Neutron upgrades.
`scripts/verify-vpc-instance-identity.sh` independently checks replica
readiness, digest pinning, matching HMAC material without printing it, the OVN
metadata upstream, ingress policies, and that the attestor Pod does not mount
a Kubernetes API token.

`reconcile-full-stack.sh` uses the patched Horizon chart's pod-local
django-compressor cache; no post-Helm ConfigMap mutation is required after the
Horizon Helm release. The chart renders the cache backend and probe timing as
declarative values, and its Deployment checksum performs any required rollout.
Interface VPC Endpoint dataplane installation is an explicit privileged-node
cutover. Build and push `vpc-endpoint-agent`, then run
`APPROVE_VPC_ENDPOINT_DATAPLANE=yes ENDPOINT_AGENT_IMAGE=<digest-reference>
VPC_ENDPOINT_POLICY_FACADE_URL=https://cloud.example/vpc-api
deploy/scripts/install-vpc-endpoint-agent.sh`. The URL must be reachable from
tenant Subnets and its certificate must be trusted by the agent image. Override
`VPC_ENDPOINT_SERVICE_CIDRS` only with reviewed internal/provider service
CIDRs. Set the same value when running `install-vpc-policy-plane.sh`; its
renderer places the allowlist in both facade and controller arguments. The
facade rejects the request, the controller refuses resource creation, and the
agent refuses forwarding outside that allowlist.
Both selected image builds and policy-plane installation refuse a dirty VPC
checkout. This prevents `git archive HEAD` images from silently omitting local
changes and prevents new working-tree CRDs from being paired with an older
locked controller binary.
The production VPC image lock covers controller, facade, metadata attestor,
and endpoint agent under one exact source revision. Identity and endpoint
cutovers reject a digest not promoted into that lock.
For an approved VPC-only rebuild, build all four components together and then
promote them atomically:

```sh
BUILD_COMPONENTS="vpc-control-plane vpc-facade vpc-metadata-attestor vpc-endpoint-agent" \
  deploy/scripts/build-images.sh
deploy/scripts/apply-rebuilt-image-lock.py --scope vpc --apply
```
Promotion updates both the Kustomize `newName` repository/tag and digest for
controller/facade, not only the digest. This is required because the selected
build path publishes all four binaries under the `openstack/project-facade`
repository with component-specific tags. The metadata-attestor and
endpoint-agent full references are recorded in the same lock transaction.

Rack-aware Magnum placement must promote the driver and repository writer
together:

```sh
BUILD_COMPONENTS="magnum-capi magnum-capi-gitops magnum-capi-repository-writer" \
  deploy/scripts/build-images.sh
deploy/scripts/apply-rebuilt-image-lock.py --scope magnum --apply
```

Selective build mode includes the repository writer before exiting; full mode
builds each VPC image once through the optimized binary/runtime path.
The installer creates matching 48-byte HMAC Secrets in the agent and facade
Namespaces without printing plaintext, rolls the facade on secret change, and
then waits for the endpoint-agent DaemonSet. Policy-bearing endpoints publish
fresh coordination Leases only after the signed policy health check succeeds.

Before P0/P1 site acceptance, run the read-only preflight. It checks the
installed CRDs, digest-pinned control plane readiness, endpoint-agent/HMAC
prerequisites, the acceptance project's credential and drift CronJob, the
live Magnum driver/renderer Rack placement contract, and the Rack BGP inputs
without changing the cluster:

```sh
VPC_ACCEPTANCE_PROJECT_NAMESPACE=vpc-<project-id> \
deploy/scripts/preflight-vpc-p0-p1-acceptance.sh
```

The preflight reads Rack membership from the infrastructure repository's
`inventory/site.yaml` and BGP approval/peer contracts from
`automation/inventory/production/group_vars/all.yml`; ad-hoc environment
strings cannot satisfy those gates. Set `DCN_INFRA_REPO` only when that
repository is checked out somewhere other than the standard sibling path.
After BGP policy approval, the preflight invokes the infrastructure
repository's read-only `57-verify-ovn-bgp-agent.yml`. It requires every Compute
agent and FRR peer to be live and at least one acceptance `/32` per Rack to
appear both on `bgp-nic` and in the peer's advertised-route view; approved inventory
alone cannot pass.
It also inspects the actually deployed Phase 54 ConfigMap/Job; having the new
template only in Git does not pass the Address Scope and gateway/FIP/LB pool
gate. Likewise, a Magnum image passes only when the driver persists the
selected AZ with its Rack external-network UUID and the live repository writer
renders that AZ into CAPO control-plane and worker failure domains.
