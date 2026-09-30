# Provider-managed egress boundary

Status: development candidate; not deployed or accepted for production.

This image change adds only the management-destination guard. It does not add
the managed NFS service-port plugin, Manila extensions, extra OVN bridges or a
tenant API. Site destinations and project enrollment belong to the production
repository's existing `cinder-manila-recovery` change contract, not this package.

The `dcn_management_guard` Neutron configuration group accepts `project_ids`
and `denied_cidrs`. Both lists default empty, which is inert. Supplying only one
list fails. IDs must be exact Keystone project IDs; destinations must be
canonical non-overlapping CIDRs, not a default route.

For enrolled projects the immutable installer hooks Neutron OVN port creation
and update in the same NB transaction. Provider-owned port-group drop ACLs use
tier 0 and priority 32767. Tenant security groups, disabled port security,
port names and device-owner strings are not opt-outs. Repair-mode Neutron
synchronization reconciles membership; log/check-only synchronization does not.
Foreign ownership or unexpected ACL drift fails instead of being overwritten.

Only normal OVN vNICs are supported. Non-normal vNICs in enrolled projects
reject; this is not SR-IOV packet enforcement. Do not enroll a mixed-vNIC project
without an accepted migration and impact plan. Unenrolled projects are unchanged.

Build through the serialized image queue using a pushed full source revision.
Promote the returned digest only after native API, create/update/restart/repair
and actual packet tests pass, including denial, allowed-service positive
controls and tenant attempts to bypass the policy. Unit or private OVSDB tests
alone do not satisfy that gate. Deployment uses the authoritative production
reconciler and its cluster-wide lock; no direct OVN edits.

An internal receipt-fenced group retirement command is under development.
It verifies the exact group UUID, owner, ACL inventory and member projects,
requires explicit writer exclusion, and deletes only the group reference.
It has no production entrypoint or qualified writer-exclusion mechanism yet.
Removing configuration or reverting the image
does not by itself remove previously written OVN port groups or ACLs. A scoped,
receipt/ownership-verified rollback and its acceptance are required before
production promotion. Do not treat an empty configuration as a live rollback.

Local source checks:

`deploy/tests/management_guard_packet_fixture.py` runs real private OVN/OVS
and Linux veth TCP endpoints on the development utility through the production
repository's `ai-space-management-packets` component. It uses compiler-generated
drop matches and checks baseline access, new and established flow denial,
allowed-destination continuity and access restoration in separate fresh
`allow-stateless` and `allow-related` datapaths. It does not execute
Neutron HTTP authorization or use a Nova VM, and currently covers IPv4 only.
Native transaction tests and this packet test are complementary, not a complete
production acceptance suite. Exact tool/source digests and execution outcomes
belong to the central change contract.

```sh
python3 -m unittest discover -s deploy/tests -p 'test_management_guard*.py'
bash -n deploy/scripts/build-images.sh
git diff --check
```
