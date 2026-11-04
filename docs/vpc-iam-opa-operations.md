# VPC IAM and OPA operations

## Enforcement model

The facade classifies every authenticated request as `read`, `project-write`,
`network-sharing`, or `security-policy`. All four classes are currently
enforced by policy version `vpc-authz-v3`. OPA errors and policy-version
mismatches fail open to the deterministic facade decision; this preserves API
availability while the deployment has only two controller failure domains.

`network-sharing` is limited to network operators and administrators.
`security-policy` covers Network ACL and Flow Log policy and is limited to
security operators and administrators. Project users retain ordinary Security
Group management through `project-write`.

## Audit and observability

Every completed facade request records request ID, stable Keystone user,
project and domain IDs, roles, method, path, authorization class, outcome,
status, and duration. Every enforced OPA decision records the same identity and
request fields plus action, resource type, policy version, and one of `allow`,
`deny`, or `fail-open`. Tokens, passwords, application credentials, and Ceph
keys must never be logged.

Grafana dashboard `VPC IAM / OPA Audit` combines:

- facade authorization outcome counters;
- OPA enforcement and fail-open counters;
- searchable OPA decision logs from Loki; and
- searchable completed-request audit logs from Loki.

`VPCOPAEnforcementFailOpen` alerts on the break-glass fallback and
`VPCFacadeAuthorizationDenialSpike` alerts when a class exceeds twenty denials
in ten minutes.

## Policy deployment and rollback

### Facade credential trust inputs

The composite installer checks that `deploy/locks/vpc-policy-images.yaml`
and `deploy/locks/vpc-facade-credential-trust.yaml` select the same facade
image and source revision before accessing Kubernetes. Changing either lock
alone is not a deployment procedure. Other component images remain separately
pinned; a facade source update must be checked for controller/CRD changes.

`install-vpc-policy-plane.sh --check` validates the facade credential generator
against the existing administrator Secret and public CA without emitting
credentials, then performs server-side dry-runs. It does not authenticate a
user or prove a successful rollout. Actual credential acceptance and rollback
remain required by the production change contract.

Facade credentials use an HTTPS identity v3 endpoint, `verify: true`, the
Secret's `cacert` data key, and `endpoint_type` (not `interface`, which the
Go client does not normalize). `VPC_IDENTITY_URL` selects the identity endpoint;
its default is the site's public identity URL. The facade Pod receives
`SSL_CERT_FILE` and a read-only `openstack-public-ca` mount. Conflicting mount
paths, environment variables, or Secret volume definitions stop rendering.
Do not disable TLS verification to resolve an incorrect CA or endpoint.

These are source behavior descriptions, not evidence of current deployment.
Production authorization, deployed revisions and acceptance are owned by the
production repository's `vpc-credential-trust` change contract.

1. Run facade unit tests and Rego tests.
2. Deploy the immutable policy ConfigMap with a new policy version.
3. Verify a canary OPA replica and the six-persona matrix.
4. Confirm zero OPA/facade mismatch before completing the rollout.
5. Confirm both OPA replicas and both facade replicas are Ready.

Immediate break-glass rollback restores deterministic facade-only decisions:

```bash
kubectl -n vpc-control-plane-system set env deployment/vpc-facade \
  OPA_ENFORCEMENT_CLASSES-
kubectl -n vpc-control-plane-system rollout status deployment/vpc-facade \
  --timeout=180s
```

Restore the Git-declared class list by applying the production facade manifest.
Use break-glass only for an OPA availability or policy incident, record the
operator and request window outside the public repository, and investigate the
corresponding Loki audit records.

Fail-closed operation is not enabled. It requires at least three independent
OPA failure domains, tested policy rollback, and an approved emergency-access
procedure.
