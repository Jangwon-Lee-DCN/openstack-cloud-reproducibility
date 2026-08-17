# Production deployment safety

The workspace-wide `/home/ubuntu/AGENTS.md` is mandatory. This repository owns
immutable artifacts, release locks, final values, patches, and reproducible
deployment inputs. It does not own live topology or UI/API behavior. Cross-repo
work must update the central change contract in `openstack-production-datacenter`.

This worktree is the portable source used by the live three-rack production
deployment. Read the parent repository's `AGENTS.md` and production inventory
before applying charts.

Feature delivery must also follow the workspace pull-request hygiene policy.
In particular, keep related implementation and acceptance-harness corrections
on one open feature branch until the complete development acceptance passes.
Do not create a new development and main promotion pair for every live probe or
diagnostic finding. A separate PR is reserved for a material product/security
defect, rollback, or independently deployable unit and must state that reason.
The normal feature budget is one feature PR and one promotion PR; source locks
and the central change contract advance only for the final accepted revision.

- Never use the PoC interface names `eno1` or `eno2` for production OpenStack
  networking.
- On Compute nodes, `dcn-ovn0` is the stable name of the dedicated physical
  10 GbE OVN/provider link.
- `dcn-geneve` is VLAN 130 on `dcn-ovn0` and is the OVN tunnel interface.
- `dcn-provider` is VLAN 140 on `dcn-ovn0` and must be attached to `br-ex`.
- Before applying OVN, decrypt only for local validation and require
  `network.interface.tunnel=dcn-geneve` and
  `conf.auto_bridge_add.br-ex=dcn-provider`.
- Stop rather than applying an OVN release that maps `br-ex` to `eno2`.
- When `dcn-image-build-queue.service` is active, every image rebuild must be
  submitted through `/usr/local/bin/dcn-image-build`. Do not invoke
  `deploy/scripts/build-images.sh`, create an ad-hoc Kaniko/BuildKit Job, push
  a competing tag, call the bundled Pueue client directly, or stop the queue
  to bypass it. Pin every source to a pushed full commit, wait for the returned
  immutable digest, and keep deployment/promotion separate. See
  `tools/image-build-queue/README.md`.

## Mandatory production acceptance

- Production deployment is forbidden until 100% of the declared acceptance
  scenarios for the changed user workflow pass against the exact immutable
  image digest and rendered values that will be promoted.
- A page returning HTTP 200, a template loading, an element existing, or Pods
  becoming Ready is not functional acceptance. Exercise the complete user
  action and its downstream API call, then assert the visible result and the
  absence of error UI and server exceptions.
- Every UI change requires an authenticated browser-equivalent E2E check for
  the changed interaction (for example: select an image, call its detail API,
  and render required fields). Static, unit, render, and readiness checks are
  additional gates and cannot replace this check.
- Run acceptance once before promotion in isolation and again against the live
  production endpoint after rollout. Record the command, artifact digest,
  HTTP/API result, and user-visible assertion. If any required assertion is
  missing, ambiguous, skipped, or fails, stop and roll back; never report the
  feature complete.
- Do not weaken, bypass, edit around, or selectively skip a failing gate to
  deploy. A gate defect must be fixed and the full acceptance rerun before
  promotion.
- Production Helm changes must run through the repository reconciler and hold
  its cluster-wide deployment lock through rollout. Direct `helm upgrade`, or
  starting another reconciliation while the lock exists, is prohibited.
- Admission-enforced immutable image locks are production safety controls.
  Never remove or bypass them to deploy; update the approved digest in source,
  pass acceptance, and reconcile the policy before the release.
