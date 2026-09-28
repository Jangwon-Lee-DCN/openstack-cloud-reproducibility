# Provider-managed service port policy inputs

This candidate is **not deployed**. It must not enable a tenant storage feature
or be used as production authorization. Site topology, allocation IDs and live
acceptance belong to production-datacenter's `cinder-manila-recovery` contract.

`deploy/scripts/render-neutron-service-port-policy.py` takes the exact release's
effective Neutron rules (defaults merged with current overrides) and an explicit
list of provider-managed network UUIDs. It wraps create/update/delete port with
an additional guard; it does not weaken the previous operation rule or change
read access. Protected networks require admin/service role in addition to the
original rule. Missing target network identity fails closed. Do not grant the
service role to tenant users. Network IDs, unlike tags or device-owner labels,
cannot be removed from an existing port to evade the guard.

No network ID or deployment value is provided by this repository. The renderer
does not fetch secrets, change live policy, create ports or attach VMs. Do not
overwrite a policy file with an incomplete defaults dictionary. Recompute from
the release's resolved policy on upgrades; repeated wrapping is rejected.

```bash
python3 deploy/tests/test_neutron_service_port_policy.py
python3 deploy/scripts/render-neutron-service-port-policy.py \
  /path/to/resolved-release-policy.json --network-id "$SERVICE_NETWORK_ID"
```

`deploy/tests/neutron_service_port_policy_engine.py:verify` runs against the
installed Neutron/oslo-policy modules using independent in-process enforcers.
It checks 24 role/network/action decisions and 12 missing-target cases. It does
not change the running API's enforcer. Engine results are not HTTP acceptance.

Before integrating a release override, isolated API tests must prove:

- Tenant direct Neutron calls cannot create, update or delete protected ports,
  including IP/MAC/SG/allowed-address-pair/port-security changes.
- VPC facade/controller cannot recreate protected ports with project credentials
  or bypass managed lifecycle; integration must use a scoped privileged path.
- Nova can bind, detach and delete a VM with a pre-created protected port without
  deleting the retained IP before Manila revocation. Test actual service-token
  behavior, not assumptions about Nova credentials.
- Ordinary project networks preserve permissions and normal VM lifecycles.
- Full and partial request targets contain the immutable network identity on
  every relevant native endpoint, including binding extensions and bulk paths.
- Provider policy guards network sharing/deletion too; packet enforcement is
  independent of editable tenant SGs, and the normal NIC cannot bypass it.

This policy compiler alone does not satisfy those gates or implement a managed
NFS service. On failure retain the previous release policy and do not expose
new service networks.
