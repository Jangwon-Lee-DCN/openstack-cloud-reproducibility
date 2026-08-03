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
