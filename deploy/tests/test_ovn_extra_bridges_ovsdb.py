"""Real private OVSDB acceptance; IP commands simulated, NOT dataplane acceptance.

OVS_TEST_ROOT points to extracted Ubuntu packages (no system installation).
Run explicitly; absence of required binaries is a failure, never a skipped pass.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest

from test_ovn_extra_bridges import ENTRY, render


class RealDatabaseTests(unittest.TestCase):
    def test_rendered_initializer_against_private_database(self):
        tools = Path(os.environ['OVS_TEST_ROOT']).resolve()
        script = render({'dcn-1b-compute-1': [ENTRY]})
        start = script.index('# BEGIN operator-selected')
        publication = script.index('ovs-vsctl set open . external-ids:ovn-bridge-mappings=', start)
        section = script[start:script.index('\n', publication)]
        with tempfile.TemporaryDirectory(prefix='nfs-real-ovsdb-') as directory:
            root = Path(directory)
            env = dict(os.environ, LD_LIBRARY_PATH=str(tools/'usr/lib/x86_64-linux-gnu'),
                       OVS_RUNDIR=str(root), OVS_LOGDIR=str(root), OVS_DBDIR=str(root))
            def run(*args, **kwargs):
                return subprocess.run(args, env=env, text=True, capture_output=True,
                                      check=True, timeout=15, **kwargs).stdout.strip()
            run(str(tools/'usr/bin/ovsdb-tool'), 'create', str(root/'db'),
                str(tools/'usr/share/openvswitch/vswitch.ovsschema'))
            server = subprocess.Popen([str(tools/'usr/sbin/ovsdb-server'),
                str(root/'db'), '--remote=punix:'+str(root/'db.sock'),
                '--unixctl='+str(root/'control.sock'), '--no-chdir'], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                for _ in range(100):
                    if (root/'db.sock').exists():
                        break
                    self.assertIsNone(server.poll(), 'Private OVSDB exited')
                    time.sleep(.02)
                self.assertTrue((root/'db.sock').exists())
                # --no-wait is intentional: no live vswitchd or kernel ports.
                command = [str(tools/'usr/bin/ovs-vsctl'), '--no-wait',
                           '--db=unix:'+str(root/'db.sock')]
                def ovs(*args):
                    return run(*command, *args)
                ovs('init')
                ovs('add-br', 'br-ex', '--', 'add-port', 'br-ex', 'dcn-provider')
                ovs('add-br', 'br-int')
                baseline = ovs('--format=json', '--columns=name,ports,external_ids', 'list', 'Bridge', 'br-ex')
                wrapper = root/'ovs-vsctl'
                wrapper.write_text('#!/bin/sh\nexec '+shlex.join(command)+' "$@"\n')
                wrapper.chmod(0o755)
                ip = root/'ip'
                ip.write_text('''#!/bin/sh
if [ "$1 $2 $3 $4" = "-d -o link show" ]; then
  echo '9: dcn-nfs-svc@dcn-storage0: <UP> mtu 1500 vlan protocol 802.1Q id 181'
fi
''')
                ip.chmod(0o755)
                env.update(PATH=str(root)+':'+os.environ['PATH'], NODE_NAME='dcn-1b-compute-1')
                def initialize():
                    return subprocess.run(['bash'], input='set -e\nbridge_mappings=external-rack-2:br-ex\n'+section,
                                          env=env, text=True, capture_output=True, timeout=20)
                for _ in range(2):
                    result = initialize()
                    self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(ovs('get', 'Open_vSwitch', '.', 'external_ids:ovn-bridge-mappings').strip('"'),
                                 'external-rack-2:br-ex,managed-nfs:br-nfs')
                self.assertEqual(ovs('port-to-br', 'dcn-nfs-svc'), 'br-nfs')
                ovs('add-port', 'br-nfs', 'patch-local', '--', 'set', 'Interface', 'patch-local',
                    'type=patch', 'options:peer=patch-peer', '--', 'set', 'Port', 'patch-local',
                    'external_ids:ovn-localnet-port=provnet-test')
                ovs('add-port', 'br-int', 'patch-peer', '--', 'set', 'Interface', 'patch-peer',
                    'type=patch', 'options:peer=patch-local', '--', 'set', 'Port', 'patch-peer',
                    'external_ids:ovn-localnet-port=provnet-test')
                result = initialize()
                self.assertEqual(result.returncode, 0, result.stderr)
                ovs('set', 'Port', 'patch-peer', 'external_ids:ovn-localnet-port=wrong')
                before = ovs('--format=json', 'list', 'Bridge')
                result = initialize()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(ovs('--format=json', 'list', 'Bridge'), before)
                self.assertEqual(ovs('--format=json', '--columns=name,ports,external_ids', 'list', 'Bridge', 'br-ex'), baseline)
                print(json.dumps({'real_ovsdb': 'pass', 'first_init': 'pass', 'repeat_init': 'pass',
                                  'ovn_patch_pair': 'pass', 'mismatch_denial': 'pass',
                                  'existing_external_bridge_unchanged': 'pass', 'ip_commands': 'simulated'}))
            finally:
                server.terminate()
                try:
                    server.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.communicate()


if __name__ == '__main__':
    unittest.main()
