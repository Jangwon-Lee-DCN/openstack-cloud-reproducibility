"""Real ovsdbapp/NB transaction contract; private synthetic database only."""
import json
import importlib.util
import inspect
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import uuid

from ovsdbapp.backend.ovs_idl import connection, idlutils
from ovsdbapp.backend.ovs_idl import command
from ovsdbapp.schema.ovn_northbound import impl_idl
from ovs.db import idl

import dcn_management_guard as guard
import dcn_management_guard_runtime as runtime
from oslo_config import cfg
from neutron.conf.plugins.ml2 import config as ml2_config
from neutron.plugins.ml2.drivers.ovn.mech_driver.ovsdb import ovn_client, ovn_db_sync, impl_idl_ovn

ARTIFACT = os.environ.get('AI_SPACE_GUARD_ARTIFACT') == '1'
if ARTIFACT:
    for module in (guard, runtime, ovn_client, ovn_db_sync):
        assert '/site-packages/' in module.__file__, module.__file__
    for module in (ovn_client, ovn_db_sync):
        assert 'import dcn_management_guard_runtime as management_guard' in inspect.getsource(module)
else:
    installer_spec = importlib.util.spec_from_file_location('guard_installer', Path(__file__).with_name('install-management-guard.py'))
    installer = importlib.util.module_from_spec(installer_spec)
    installer_spec.loader.exec_module(installer)
    for module, kind in [(ovn_client, 'client'), (ovn_db_sync, 'sync')]:
        patched = installer.transform(inspect.getsource(module), kind)
        compile(patched, module.__file__, 'exec')


def exercise_installed_client(conn, project, policy):
    """Execute transformed upstream methods with real Neutron NB commands.

    DHCP/DNS/QoS and SQL revision bookkeeping are stubbed: this verifies the
    OVN transaction boundary, not HTTP authorization or guest networking.
    """
    namespace = dict(vars(ovn_client))
    ml2_config.register_ml2_plugin_opts()
    if not ARTIFACT:
        exec(compile(installer.transform(inspect.getsource(ovn_client), 'client'),
                     ovn_client.__file__, 'exec'), namespace)
    nb = impl_idl_ovn.OvsdbNbOvnIdl(conn)
    client = namespace['OVNClient'](nb, None)
    network = str(uuid.uuid4())
    nb.ls_add('neutron-'+network).execute(check_error=True)
    nb.pg_add('neutron_pg_drop', may_exist=True).execute(check_error=True)
    port = {'id': str(uuid.uuid4()), 'network_id': network, 'project_id': project,
            'name': 'ordinary-port', 'device_owner': 'compute:nova',
            'device_id': '', 'admin_state_up': True, 'security_groups': [],
            'port_security_enabled': False, 'binding:vnic_type': 'normal',
            'revision_number': 1, 'allowed_address_pairs': [], 'fixed_ips': []}
    info = SimpleNamespace(addresses=['unknown'], parent_name=[], tag=[],
                           options={}, type='', port_security=[])
    client.get_external_ids_from_port = lambda context, value: (
        info, {'neutron:project_id': value['project_id']})
    client.update_port_dhcp_options = lambda *args, **kwargs: ([], [])
    client.is_dns_required_for_port = lambda value: False
    client._set_unset_virtual_port_type = mock.Mock()
    client._qos_driver = mock.Mock()
    context = mock.Mock()
    with mock.patch.object(namespace['db_rev'], 'bump_revision'):
        client.create_port(context, port)
        group = nb.lookup('Port_Group', policy[project]['name'])
        assert port['id'] in {p.name for p in group.ports}
        # Update must restore membership even when SG/port-security are absent.
        nb.pg_del_ports(group.name, port['id']).execute(check_error=True)
        client.update_port(context, dict(port, revision_number=2, admin_state_up=False), port)
        assert nb.lookup('Logical_Switch_Port', port['id']).enabled == [False]
        group = nb.lookup('Port_Group', group.name)
        assert port['id'] in {p.name for p in group.ports}
        acl = group.acls[0]
        nb.db_set('ACL', acl.uuid, ('action', 'allow')).execute(check_error=True)
        try:
            client.update_port(context, dict(port, revision_number=3), port)
        except ValueError as error:
            assert 'Managed ACL drift' in str(error)
        else:
            raise AssertionError('Upstream update committed despite guard failure')
        assert nb.lookup('Logical_Switch_Port', port['id']).enabled == [False]
        nb.db_set('ACL', acl.uuid, ('action', 'drop')).execute(check_error=True)
    client._qos_driver.create_port.assert_called_once()

REMOTE = 'unix:/state/nb.sock'
helper = idlutils.get_schema_helper(REMOTE, 'OVN_Northbound')
helper.register_all()
conn = connection.Connection(idl.Idl(REMOTE, helper), timeout=10)
api = impl_idl.OvnNbApiIdlImpl(conn)
project = uuid.uuid4().hex
foreign_project = uuid.uuid4().hex
policy = guard.compile_policy([project, foreign_project], ['198.18.40.0/24', '2001:db8:40::/64'])
assert runtime.policy() == {}, 'Runtime must be inert by default'
assert runtime.enqueue_port(None, None, {}) is False
cfg.CONF.set_override('project_ids', [project, foreign_project], group=runtime.GROUP)
cfg.CONF.set_override('denied_cidrs', ['198.18.40.0/24', '2001:db8:40::/64'], group=runtime.GROUP)
assert runtime.policy() == policy
switch = 'guard-test-'+str(uuid.uuid4())
api.ls_add(switch).execute(check_error=True)


def create(project_id, expected_failure=None):
    port_id = str(uuid.uuid4())
    error = None
    try:
        with api.transaction(check_error=True) as txn:
            txn.add(api.lsp_add(switch, port_id,
                external_ids={'neutron:project_id': project_id}, port_security=[]))
            runtime.enqueue_port(api, txn, {'id': port_id, 'project_id': project_id,
                'security_groups': [], 'port_security_enabled': False, 'device_id': ''})
    except Exception as caught:
        error = caught
    if expected_failure:
        assert error is not None, 'Expected guard failure was not raised'
        assert isinstance(error, ValueError) and expected_failure in str(error), repr(error)
        assert api.lookup('Logical_Switch_Port', port_id, default=None) is None, 'Unguarded LSP committed'
    elif error:
        raise error
    return port_id


try:
    first, second = create(project), create(project)
    group = api.lookup('Port_Group', policy[project]['name'])
    assert {port.name for port in group.ports} == {first, second}
    assert len(group.acls) == 2
    for _ in range(2):
        with api.transaction(check_error=True) as txn:
            runtime.enqueue_port(api, txn, {'id': first, 'project_id': project})
    group = api.lookup('Port_Group', policy[project]['name'])
    assert len(group.acls) == 2 and len(group.ports) == 2

    # Foreign ownership must abort both the new LSP and guard transaction.
    api.pg_add(policy[foreign_project]['name'], external_ids={'other-owner': 'true'}).execute(check_error=True)
    create(foreign_project, expected_failure='Refusing to adopt foreign port group')

    # A changed allow action cannot be mistaken for an installed drop.
    acl = group.acls[0]
    api.db_set('ACL', acl.uuid, ('action', 'allow')).execute(check_error=True)
    create(project, expected_failure='Managed ACL drift')
    api.db_set('ACL', acl.uuid, ('action', 'drop')).execute(check_error=True)

    # Repair a missing owned ACL when a new port is created, in one transaction.
    api.db_remove('Port_Group', group.uuid, 'acls', acl.uuid).execute(check_error=True)
    third = create(project)
    group = api.lookup('Port_Group', policy[project]['name'])
    assert len(group.acls) == 2
    assert {port.name for port in group.ports} == {first, second, third}

    # Deletion uses the NB weak reference, leaving no stale member after LSP removal.
    api.lsp_del(second).execute(check_error=True)
    group = api.lookup('Port_Group', policy[project]['name'])
    assert {port.name for port in group.ports} == {first, third}

    # Real DB repair through the runtime adapter after a complete PG loss.
    api.pg_del(policy[project]['name']).execute(check_error=True)
    ports = [{'id': port_id, 'project_id': project, 'device_owner': 'compute:nova',
              'binding:vnic_type': 'normal'} for port_id in (first, third)]
    def get_ports(context, filters):
        assert filters == {'project_id': sorted(policy)}
        return ports
    runtime.repair_ports(api, SimpleNamespace(get_ports=get_ports), None)
    group = api.lookup('Port_Group', policy[project]['name'])
    assert len(group.acls) == 2 and {p.name for p in group.ports} == {first, third}
    ports.append(dict(ports[0], id=str(uuid.uuid4())))
    try:
        runtime.repair_ports(api, SimpleNamespace(get_ports=get_ports), None)
    except RuntimeError as error:
        assert 'Enrolled LSP missing' in str(error)
    else:
        raise AssertionError('Missing enrolled LSP incorrectly qualified after synchronization')
    exercise_installed_client(conn, project, policy)
    class RetireGuard(command.BaseCommand):
        def __init__(self, database, expected, fenced):
            super().__init__(database)
            self.expected, self.fenced = expected, fenced
        def run_idl(self, txn):
            guard.retire_in_transaction(self.api, policy[project], self.expected, lambda: self.fenced)
    group = api.lookup('Port_Group', policy[project]['name'])
    original_uuid = str(group.uuid)
    protected_ports = {p.name for p in group.ports}
    for expected, fenced in ((str(uuid.uuid4()), True), (original_uuid, False)):
        try:
            with api.transaction(check_error=True) as txn:
                txn.add(RetireGuard(api, expected, fenced))
        except ValueError:
            pass
        else:
            raise AssertionError('Unqualified retirement accepted')
        assert str(api.lookup('Port_Group', policy[project]['name']).uuid) == original_uuid
    with api.transaction(check_error=True) as txn:
        txn.add(RetireGuard(api, original_uuid, True))
    assert api.lookup('Port_Group', policy[project]['name'], default=None) is None
    assert all(api.lookup('Logical_Switch_Port', name, default=None) is not None for name in protected_ports)
    assert api.lookup('Port_Group', policy[foreign_project]['name']).external_ids == {'other-owner': 'true'}
    print(json.dumps({'same_transaction_port_and_guard': True, 'extra_port_guarded': True,
                      'foreign_group_aborts_port_creation': True, 'drift_aborts_port_creation': True,
                      'repeat_no_duplicate_acls': True, 'missing_acl_repaired': True,
                      'deleted_port_membership_removed': True, 'full_group_repair': True,
                      'missing_lsp_refused': True, 'installed_neutron_hook_shape_compiles': True,
                      'default_configuration_inert': True, 'compact_keystone_ids': True,
                      'installed_client_create_update_transaction': True,
                      'installed_client_update_failure_atomic': True,
                      'receipt_fenced_retirement_preserves_ports_and_foreign_group': True,
                      'packaged_artifact_without_source_override': ARTIFACT}))
finally:
    conn.stop()
