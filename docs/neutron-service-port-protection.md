# Provider-managed service-port boundary

This opt-in artifact is not production activation. It does not create networks,
enroll resource IDs, change current policies, expose a UI or grant storage access.
Production owns enrollment, topology, acceptance, activation and rollback in
the `cinder-manila-recovery` change contract. Merely importing the module does
not register callbacks.

## Configuration

`deploy/scripts/render-neutron-service-port-policy.py` consumes the release's
complete effective policy (defaults plus overrides). Repeated `--network-id`
arguments select exact canonical protected network UUIDs. Port create, update
and delete rules retain their original checks and add the managed boundary;
missing network identity fails closed. Read policy remains unchanged.

Supply every existing plugin with repeated `--service-plugin` arguments to
render a Helm override preserving those plugins and appending
`dcn_service_port_guard.ServicePortGuard`. The plugin requires a nonempty
`dcn_service_ports.network_ids` list. It checks original network identity in
native port callbacks, including plugin-internal router interface operations.
An unchanged rollback update is allowed, but real tenant mutations are denied.

ML2 binding activation is a separate member action, not an ordinary port update.
When explicitly enabled, the plugin also guards the core `activate` entrypoint:
it reads the stored port network and rejects non-admin/non-service activation of
protected ports. Both direct UUID and the installed Pecan body-dictionary calling
forms are handled. Import alone does not modify the core plugin. The native
fixture checks member denial with unchanged binding state and service activation
with an independently observed ACTIVE binding. This is not a claim that every
binding extension or the real Nova service-token flow has passed acceptance.

Optional repeated `--security-group-id` arguments select explicit protected
groups in `dcn_service_ports.security_group_ids`. Native callbacks reject member
group update/delete and rule create/delete. Rule deletion resolves the stored
rule's group. Empty group enrollment adds no group callbacks. Provider-owned
groups remain required; this option is defense in depth, not permission to use
tenant-editable groups for storage protection.

Admin/service contexts bypass only this additional denial, not original API
authorization. Never assign the service role to tenant actors. This guard is
not a management-egress firewall, Manila access grant, guest file permission,
share-worker HA mechanism or protection against privileged operators.

## Artifact and acceptance

The serialized `neutron-fwaas` build stages the authoritative module from
`deploy/neutron/` into the existing digest-pinned image. It does not include or
activate a management-egress hook. Submit the exact pushed source through the
image queue; never invoke the underlying builder directly.

Local checks:

```bash
python3 deploy/tests/test_neutron_service_port_policy.py
bash -n deploy/scripts/build-images.sh
```

The policy test renders the packaged Helm chart and checks policy preservation,
resource validation and plugin configuration. The native API test uses installed
Neutron WSGI/ML2 with SQLite and injected project contexts. The production-owned
`ai-space-neutron-api` isolated development component stages that test and runs
it with a pinned fixture image; `AI_SPACE_REPRO_ROOT` selects this source and
`AI_SPACE_NEUTRON_IMAGE` selects an immutable built candidate. Candidate mode
checks the installed module hash and does not mount replacement runtime code.

Native coverage includes protected port CRUD denial/unchanged objects, normal
port lifecycle, mixed protected/ordinary bulk denial without partial creation,
ordinary-only bulk success/cleanup, router port/subnet attach denial, ML2 test-agent binding, protected
group/rule mutation denial, ordinary group rule CRUD and privileged cleanup.
It is not Keystone authentication, real OVN binding or CPU packet acceptance.

Before activation, qualify authenticated native endpoints including bulk/binding
extensions, Nova service-token attach/detach/delete and retained address lifecycle,
VPC privileged integration, ordinary VM regressions and real CPU NFS RW/RO/isolation.
Management-NIC bypass blocking is a separate required integration. Never expose
the service network from only a successful build or native fixture result.

Rollback must use the previous accepted immutable image and policy through the
authoritative reconciler. Quiesce managed provisioning and preserve retained
ports/addresses until Manila access is revoked; do not silently remove protection
while managed storage remains reachable.
