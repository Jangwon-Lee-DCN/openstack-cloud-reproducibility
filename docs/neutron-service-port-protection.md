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

`deploy/tests/test_neutron_service_port_api.py` additionally exercises Neutron's
WSGI request handlers, ML2 Open vSwitch mechanism driver and a temporary SQLite DB.
The production repository runs it with `./deploy.sh development
ai-space-neutron-api` on the utility node using the immutable Neutron image,
without production configuration, credentials or service-account token. Missing
test dependencies are supplied only to that fixture with version/SHA256 pins;
ConfigMap source hashes must match before execution. Member+reader requests
must be able to GET the protected port, but CREATE/UPDATE/DELETE are forbidden;
each denied update/delete must leave the original DB object unchanged. Covered
changes include name, fixed IP, device owner, MAC, SG removal, port-security
disablement, allowed-address-pairs and vNIC type. A separate ordinary-network
test requires successful member CREATE/UPDATE/DELETE. A test-only OVS agent
record permits checking the ML2 binding decision (`ovs`, then `unbound`), host,
and retained IP/MAC. No OVS agent process, switch, OVN chassis or Nova VM exists
in this fixture; this must not be represented as live dataplane acceptance.

This is in-process WSGI/ML2 API authorization acceptance. Keystone token
authentication, live OVN binding, bulk/binding-extension endpoints, actual Nova
VM lifecycle and NFS packet paths are not qualified by this fixture.

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

### Additional acceptance gates

HTTP 200 for a privileged port update is insufficient: reject
`binding:vif_type=binding_failed`. The installed ML2 test mechanism driver
raised an internal assertion during the first bind/unbind probe even though
the request returned 200. This is failed binding evidence, not proof of a
working Nova attachment. The fixture now uses the actual OVS mechanism driver
with an isolated test agent record and asserts exact `ovs`/`unbound` results,
rather than accepting any HTTP 200. Production OVN qualification remains open.

Router `add_router_interface` is a separate mutation surface. It can call the
core plugin without traversing the ordinary port API policy check. Test the
port-ID path as well as the subnet-ID path before treating ports as immutable;
an unattached retained port must not become a tenant router interface.
Port CRUD authorization alone cannot establish this guarantee.

The candidate `deploy/neutron/dcn_service_port_guard.py` therefore adds a
plugin-level guard on PORT BEFORE_CREATE/UPDATE/DELETE callbacks. It selects
the immutable network from original state, not the update body. A project
user's actual mutation is rejected; an unchanged rollback write is permitted.
The service plugin refuses empty or malformed protected-network configuration.
Its image build context now includes the module, but it remains **development-only
and not enabled in production**. Merely importing the class registers no
callbacks and changes no policy. The image build validates import only; no
candidate image build or rollout is implied by the Dockerfile change.
Service/admin contexts remain privileged and must never be available to tenant
callers; delegated service operations need separate acceptance. The current
fixture specifically exercises router port-ID and subnet-ID attachment and
asserts no new port or changed original port after denial.

Nova integration must additionally qualify project-scoped visibility of the
provider network, even when the port is pre-created. External network DNS
updates may use the user's Neutron client, unlike privileged port binding.
Service-network DNS settings and network sharing therefore need explicit
acceptance; changing ordinary tenant DNS or sharing the network globally is
not an acceptable workaround.

The service port must use a **provider-owned** security group, not a mutable
project default group. The isolated suite now also creates an explicit
TCP-2049-only egress group (removing default allow-all rules), attaches it to a
project-owned port as admin, and denies member attempts to add/remove rules,
rename or delete the group. The authoritative group remains unchanged after
each denied operation. This is SG ownership/API acceptance, not an OVN packet
test. In particular, adding this SG alongside an allow-all group does not
implement a deny rule on a normal tenant NIC.

### Candidate deployment inputs

The policy renderer can emit a Helm values override when given every current
service plugin through repeated `--service-plugin` arguments. It preserves
those plugins, appends `dcn_service_port_guard.ServicePortGuard`, sets explicit
`dcn_service_ports.network_ids`, and includes the complete guarded policy.
Missing/duplicate plugin lists and an already-enabled guard are rejected.
Production site values remain unchanged; do not merge this override until the
native API and actual Nova lifecycle acceptance gates pass.

The serialized `neutron-fwaas` build stages the single authoritative module
from `deploy/neutron/` into its build context. It must not maintain a second
copy under the image directory. Builds still require a pushed exact source
revision through the queue; these source changes do not authorize a build or
promotion by themselves.
