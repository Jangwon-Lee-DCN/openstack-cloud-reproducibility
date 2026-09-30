"""Opt-in management-egress compiler and transactional OVN IDL hook.

OVNClient integration must enqueue the hook in the same transaction as each
enrolled project's LSP. The immutable installer supplies those integration
points. No standalone production apply entry point exists; SR-IOV is unsupported.
"""
import ipaddress
import re
import uuid


OWNER = 'dcn:management-guard'


def canonical_uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Explicit canonical UUID required')
    return value


def compile_policy(project_ids, denied_cidrs):
    if not isinstance(project_ids, list) or not isinstance(denied_cidrs, list):
        raise ValueError('Explicit project and CIDR lists required')
    if not project_ids and not denied_cidrs:
        return {}
    if not project_ids or not denied_cidrs:
        raise ValueError('Enrollment and denied destinations must be specified together')
    projects = []
    for value in project_ids:
        # Keystone commonly uses compact 32-hex IDs; keep its exact identity
        # rather than converting it to a hyphenated Neutron resource UUID.
        if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value):
            raise ValueError('Explicit lowercase Keystone project ID required')
        projects.append(value)
    if len(set(projects)) != len(projects):
        raise ValueError('Duplicate project enrollment')
    if len({value.replace('-', '') for value in projects}) != len(projects):
        raise ValueError('Project identities collide in the port-group namespace')
    networks = []
    for value in denied_cidrs:
        network = ipaddress.ip_network(value, strict=True)
        if str(network) != value or network.prefixlen == 0:
            raise ValueError('Canonical non-default denied CIDRs required')
        if any(network.version == prior.version and network.overlaps(prior) for prior in networks):
            raise ValueError('Duplicate or overlapping denied CIDRs')
        networks.append(network)
    result = {}
    for project in sorted(projects):
        name = 'dcn_mgmt_'+project.replace('-', '')
        owner = {OWNER: 'v1', 'dcn:project_id': project}
        acls = []
        for family in (4, 6):
            cidrs = sorted(str(n) for n in networks if n.version == family)
            if not cidrs:
                continue
            acls.append({'direction': 'from-lport', 'priority': 32767, 'tier': 0,
                'match': 'inport == @'+name+' && ip'+str(family)+'.dst == {'+', '.join(cidrs)+'}',
                'action': 'drop', 'log': False, 'options': {},
                'external_ids': dict(owner, **{'dcn:ip_version': str(family)})})
        result[project] = {'name': name, 'external_ids': owner, 'acls': acls}
    return result


def plan_port(port, policy):
    project = port.get('project_id') or port.get('tenant_id')
    if ((port.get('project_id') in policy or port.get('tenant_id') in policy)
            and port.get('project_id') and port.get('tenant_id')
            and port['project_id'] != port['tenant_id']):
        raise ValueError('Conflicting port project identities')
    if project not in policy:
        return None
    port_id = canonical_uuid(port['id'])
    if port.get('binding:vnic_type', 'normal') != 'normal':
        raise ValueError('Enrolled project requires a qualified OVN normal-vNIC path')
    # Never key opt-out on SG attachment, port security, tags, names, owner
    # strings or an empty device_id. A second unbound NIC is protected too.
    return {'port_id': port_id, 'port_group': policy[project]}


def apply_in_transaction(api, transaction, plan):
    """IDL transaction body; no commit or stand-alone database connection.

    Called only after LSP creation/update in that SAME transaction. Any error
    aborts the whole transaction, so ownership failure cannot publish a newly
    created unguarded LSP. Policy replacement/removal is deliberately absent.
    """
    desired = plan['port_group']
    port = api.lookup('Logical_Switch_Port', plan['port_id'])
    port.verify('external_ids')
    if port.external_ids.get('neutron:project_id') != desired['external_ids']['dcn:project_id']:
        raise ValueError('OVN LSP project does not match enrolled Neutron port')
    group = api.lookup('Port_Group', desired['name'], default=None)
    if group is not None:
        group.verify('external_ids')
        group.verify('acls')
        if group.external_ids != desired['external_ids']:
            raise ValueError('Refusing to adopt foreign port group')
        existing = {}
        for acl in group.acls:
            for key in ('external_ids', 'match', 'action', 'priority', 'direction', 'tier', 'options'):
                acl.verify(key)
            match = acl.match
            candidates = [item for item in desired['acls'] if item['match'] == match]
            if match in existing or len(candidates) != 1:
                raise ValueError('Unexpected or duplicate managed ACL; explicit policy migration required')
            if any(getattr(acl, key) != value for key, value in candidates[0].items() if key != 'log'):
                raise ValueError('Managed ACL drift; refusing to claim enforcement')
            existing[match] = acl
    else:
        group = transaction.insert(api._tables['Port_Group'])
        group.name, group.external_ids = desired['name'], desired['external_ids']
        group.acls, group.ports = [], []
        existing = {}
    created = []
    for item in desired['acls']:
        if item['match'] not in existing:
            acl = transaction.insert(api._tables['ACL'])
            for key, value in item.items():
                setattr(acl, key, value)
            created.append(acl)
    if created:
        # IDL addvalue mutations are not necessarily visible to a later
        # command's attribute read in this same transaction. Publish the whole
        # verified ACL reference set as a column write, so a second enrolled
        # port cannot recreate the same rules during batch repair.
        group.acls = list(existing.values())+created
    group.addvalue('ports', port)


def enqueue_port(api, transaction, port, policy):
    """Candidate OVNClient hook; disabled policies import no additional runtime."""
    plan = plan_port(port, policy)
    if plan is None:
        return False
    from ovsdbapp.backend.ovs_idl import command

    class EnsureManagementGuard(command.BaseCommand):
        def run_idl(self, txn):
            apply_in_transaction(self.api, txn, plan)

    transaction.add(EnsureManagementGuard(api))
    return True


def retire_in_transaction(api, desired, expected_uuid, qualify_writers_fenced):
    """Withdraw an exact recorded group only after external writers are fenced.

    The owning reconciler must disable enrollment on all writers and retain its
    deployment lock/receipt. This is not a public API or an automatic fallback.
    No port or ACL row is explicitly deleted; OVSDB handles unreferenced rows.
    """
    canonical_uuid(expected_uuid)
    if qualify_writers_fenced() is not True:
        raise ValueError('Explicit management-guard writer fence required')
    group = api.lookup('Port_Group', desired['name'], default=None)
    if group is None:
        return False
    if str(group.uuid) != expected_uuid:
        raise ValueError('Recorded management port group was replaced')
    for key in ('name', 'external_ids', 'acls', 'ports'):
        group.verify(key)
    if group.name != desired['name'] or group.external_ids != desired['external_ids']:
        raise ValueError('Foreign management port group cannot be retired')
    expected = {item['match']: item for item in desired['acls']}
    observed = set()
    for acl in group.acls:
        for key in ('external_ids', 'match', 'action', 'priority', 'direction', 'tier', 'options', 'log'):
            acl.verify(key)
        if acl.match in observed or acl.match not in expected:
            raise ValueError('Unexpected managed ACL during retirement')
        if any(getattr(acl, key) != value for key, value in expected[acl.match].items()):
            raise ValueError('Managed ACL changed before retirement')
        observed.add(acl.match)
    if observed != set(expected):
        raise ValueError('Incomplete managed ACL inventory')
    for port in group.ports:
        port.verify('external_ids')
        if port.external_ids.get('neutron:project_id') != desired['external_ids']['dcn:project_id']:
            raise ValueError('Foreign port in managed group')
    if qualify_writers_fenced() is not True:
        raise ValueError('Management-guard writer fence lost')
    group.delete()
    return True
