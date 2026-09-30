import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('guard_installer', Path(__file__).resolve().parents[1]/'neutron/install-management-guard.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
CLIENT = m.ANCHOR+'''class OVNClient:
    def create_port(self, context, port):
        with self._nb_idl.transaction() as txn:
            self._qos_driver.create_port(context, txn, port, port_cmd)
    def update_port(self, context, port, port_object):
        with self._nb_idl.transaction() as txn:
            self._qos_driver.update_port(context, txn, port, port_object)
'''
SYNC = m.ANCHOR+'''class OvnNbSynchronizer:
    def do_sync(self):
        self.sync_networks_ports_and_dhcp_opts(ctx)
        self.sync_acls(ctx)
'''


class HooksTests(unittest.TestCase):
    def test_build_context_contains_hooks_and_nonroot_default_check(self):
        root = Path(__file__).resolve().parents[2]
        script = (root/'deploy/scripts/build-images.sh').read_text()
        docker = (root/'images/neutron-fwaas/Dockerfile').read_text()
        for filename in ('dcn_management_guard.py', 'dcn_management_guard_runtime.py',
                         'install-management-guard.py'):
            self.assertIn('"$REPO_ROOT/deploy/neutron/'+filename+'"', script)
            self.assertIn(filename, docker)
        self.assertIn('--site-packages /var/lib/openstack/lib/python3.12/site-packages', docker)
        self.assertIn('assert guard.policy() == {}', docker.split('USER neutron', 1)[1])
        self.assertNotIn('dcn_service_port_guard', docker)
        self.assertNotIn('dcn_service_port_guard', script)

    def test_exact_create_update_and_repair_hooks(self):
        client = m.transform(CLIENT, 'client')
        self.assertEqual(client.count('management_guard.enqueue_port(self._nb_idl, txn, port)'), 2)
        sync = m.transform(SYNC, 'sync')
        self.assertIn('if self.mode == ovn_const.OVN_DB_SYNC_MODE_REPAIR:', sync)
        self.assertLess(sync.index('management_guard.repair_ports('), sync.index('self.sync_acls(ctx)'))

    def test_drift_wrong_method_and_double_patch_fail(self):
        for source in (CLIENT.replace('def create_port(', 'def other('),
                       CLIENT.replace('port, port_cmd)', 'port)'), m.transform(CLIENT, 'client')):
            with self.assertRaises(ValueError):
                m.transform(source, 'client')


if __name__ == '__main__':
    unittest.main()
