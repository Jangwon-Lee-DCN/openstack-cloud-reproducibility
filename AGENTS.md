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
