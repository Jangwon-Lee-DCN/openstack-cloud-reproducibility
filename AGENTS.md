# Production deployment safety

This worktree is the portable source used by the live three-rack production
deployment. Read the parent repository's `AGENTS.md` and production inventory
before applying charts.

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

