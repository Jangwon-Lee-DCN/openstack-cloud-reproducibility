import copy
import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('management_guard', Path(__file__).resolve().parents[1]/'neutron/dcn_management_guard.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
PROJECT = '11111111-1111-4111-8111-111111111111'
PORT = '22222222-2222-4222-8222-222222222222'


class GuardTests(unittest.TestCase):
    def retirement_fixture(self):
        desired = m.compile_policy([PROJECT], ['198.18.40.0/24'])[PROJECT]
        acl = SimpleNamespace(**copy.deepcopy(desired['acls'][0]), verify=Mock())
        port = SimpleNamespace(external_ids={'neutron:project_id': PROJECT}, verify=Mock())
        group = SimpleNamespace(uuid=PORT, name=desired['name'], external_ids=copy.deepcopy(desired['external_ids']),
                                acls=[acl], ports=[port], verify=Mock(), delete=Mock())
        return desired, group, SimpleNamespace(lookup=Mock(return_value=group))

    def test_retirement_requires_exact_receipt_and_fence(self):
        desired, group, api = self.retirement_fixture()
        fence = Mock(return_value=True)
        self.assertTrue(m.retire_in_transaction(api, desired, PORT, fence))
        group.delete.assert_called_once()
        self.assertEqual(fence.call_count, 2)
        api.lookup.return_value = None
        self.assertFalse(m.retire_in_transaction(api, desired, PORT, fence))

    def test_retirement_rejects_foreign_drifted_or_unfenced_state(self):
        for mutate in (lambda g: setattr(g, 'uuid', PROJECT),
                       lambda g: setattr(g, 'external_ids', {}),
                       lambda g: setattr(g.acls[0], 'action', 'allow'),
                       lambda g: setattr(g.acls[0], 'log', True),
                       lambda g: setattr(g, 'acls', []),
                       lambda g: g.acls.append(g.acls[0]),
                       lambda g: setattr(g.ports[0], 'external_ids', {})):
            desired, group, api = self.retirement_fixture()
            mutate(group)
            with self.assertRaises(ValueError):
                m.retire_in_transaction(api, desired, PORT, lambda: True)
            group.delete.assert_not_called()
        for values in ([False], [None], [True, False]):
            desired, group, api = self.retirement_fixture()
            with self.assertRaises(ValueError):
                m.retire_in_transaction(api, desired, PORT, Mock(side_effect=values))
            group.delete.assert_not_called()

    def test_real_keystone_compact_project_ids_are_preserved(self):
        project = PROJECT.replace('-', '')
        policy = m.compile_policy([project], ['198.18.40.0/24'])
        self.assertIn(project, policy)
        self.assertEqual(policy[project]['external_ids']['dcn:project_id'], project)
        self.assertIsNotNone(m.plan_port({'id': PORT, 'project_id': project}, policy))
        with self.assertRaises(ValueError):
            m.compile_policy([PROJECT, project], ['198.18.40.0/24'])

    def test_transaction_body_owns_rows_and_repairs_missing_acl(self):
        class Row(SimpleNamespace):
            def verify(self, column):
                pass
            def addvalue(self, column, value):
                if column == 'acls':
                    # Model native IDL mutation visibility: pending set-add
                    # does not update the value read by the next command.
                    self.pending_acls = getattr(self, 'pending_acls', [])+[value]
                    return
                values = getattr(self, column)
                if value not in values:
                    values.append(value)
        port = Row(external_ids={'neutron:project_id': PROJECT})
        groups = []
        class Txn:
            def insert(self, table):
                row = Row()
                if table == 'Port_Group':
                    groups.append(row)
                return row
        def lookup(table, name, default=None):
            return port if table == 'Logical_Switch_Port' else next((g for g in groups if g.name == name), default)
        api = SimpleNamespace(lookup=lookup, _tables={'Port_Group': 'Port_Group', 'ACL': 'ACL'})
        plan = m.plan_port({'id': PORT, 'project_id': PROJECT}, m.compile_policy([PROJECT], ['198.18.40.0/24']))
        for _ in range(2):
            m.apply_in_transaction(api, Txn(), plan)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].ports), 1)
        self.assertEqual(len(groups[0].acls), 1)
        groups[0].acls = []
        m.apply_in_transaction(api, Txn(), plan)
        self.assertEqual(len(groups[0].acls), 1)
        groups[0].acls[0].action = 'allow'
        with self.assertRaises(ValueError):
            m.apply_in_transaction(api, Txn(), plan)
        groups[0].external_ids = {}
        with self.assertRaises(ValueError):
            m.apply_in_transaction(api, Txn(), plan)

    def test_disabled_is_inert_and_unenrolled_project_is_unchanged(self):
        self.assertEqual(m.compile_policy([], []), {})
        self.assertIsNone(m.plan_port({'id': PORT, 'project_id': PROJECT}, {}))
        policy = m.compile_policy([PROJECT], ['198.18.40.0/24'])
        self.assertIsNone(m.plan_port({'id': PORT, 'project_id': PORT, 'binding:vnic_type': 'direct'}, policy))

    def test_canonical_dual_stack_owned_drop_not_sg_allow(self):
        policy = m.compile_policy([PROJECT], ['2001:db8:40::/64', '198.18.40.0/24'])
        group = policy[PROJECT]
        self.assertEqual(group['name'], 'dcn_mgmt_'+PROJECT.replace('-', ''))
        self.assertEqual(len(group['acls']), 2)
        for acl in group['acls']:
            self.assertEqual((acl['priority'], acl['tier'], acl['action']), (32767, 0, 'drop'))
            self.assertNotIn('neutron:security_group_rule_id', acl['external_ids'])
            self.assertEqual(acl['external_ids'][m.OWNER], 'v1')

    def test_user_mutable_port_attributes_cannot_opt_out(self):
        policy = m.compile_policy([PROJECT], ['198.18.40.0/24'])
        port = {'id': PORT, 'project_id': PROJECT, 'binding:vnic_type': 'normal'}
        expected = m.plan_port(port, policy)
        before = copy.deepcopy(policy)
        for changes in ({'security_groups': []}, {'port_security_enabled': False},
                        {'device_owner': 'network:router_interface'}, {'name': 'exempt'},
                        {'tags': ['skip-guard']}, {'device_id': ''}):
            self.assertEqual(m.plan_port(dict(port, **changes), policy), expected)
        self.assertEqual(policy, before)

    def test_unqualified_direct_paths_fail_not_silently_bypass(self):
        policy = m.compile_policy([PROJECT], ['198.18.40.0/24'])
        for vnic in ('direct', 'direct-physical', 'macvtap', 'virtio-forwarder', ''):
            with self.subTest(vnic=vnic), self.assertRaises(ValueError):
                m.plan_port({'id': PORT, 'project_id': PROJECT, 'binding:vnic_type': vnic}, policy)

    def test_ambiguous_or_overbroad_policy_is_rejected(self):
        for projects, cidrs in (([PROJECT], []), ([], ['198.18.40.0/24']),
            ([PROJECT, PROJECT], ['198.18.40.0/24']), ([PROJECT], ['0.0.0.0/0']),
            ([PROJECT], ['198.18.40.1/24']), ([PROJECT], ['198.18.40.0/24', '198.18.40.1/32'])):
            with self.subTest(projects=projects, cidrs=cidrs), self.assertRaises(ValueError):
                m.compile_policy(projects, cidrs)

    def test_conflicting_project_fields_are_rejected(self):
        policy = m.compile_policy([PROJECT], ['198.18.40.0/24'])
        with self.assertRaises(ValueError):
            m.plan_port({'id': PORT, 'project_id': PROJECT, 'tenant_id': PORT}, policy)
        with self.assertRaises(ValueError):
            m.plan_port({'id': PORT, 'project_id': PORT, 'tenant_id': PROJECT}, policy)


if __name__ == '__main__':
    unittest.main()
