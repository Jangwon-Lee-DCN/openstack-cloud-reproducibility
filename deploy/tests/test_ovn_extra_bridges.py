"""Rendered chart contract. Runtime stubs are not live OVS/OVN acceptance."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
ENTRY = {'physnet': 'managed-nfs', 'bridge': 'br-nfs', 'interface': 'dcn-nfs-svc', 'parent': 'dcn-storage0', 'vlan': 181}


def render(extra=None, chart=None, expected=0):
    args = ['helm', 'template', 'ovn', str(chart or ROOT/'helm/openstack-helm/ovn'), '-f', str(ROOT/'deploy/values/site/ovn.yaml')]
    if extra is not None:
        args += ['--set-json', 'conf.ovn_node_extra_bridges='+json.dumps(extra)]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != expected:
        raise AssertionError(result.stderr)
    if expected:
        return
    config = next(d for d in yaml.safe_load_all(result.stdout) if d and d.get('kind') == 'ConfigMap' and d['metadata']['name'] == 'ovn-bin')
    script = config['data']['ovn-controller-init.sh']
    subprocess.run(['bash', '-n'], input=script, text=True, check=True)
    return script


class ExtraBridgeTests(unittest.TestCase):
    def test_disabled_render_preserves_packaged_initializer(self):
        current = render()
        # Frozen before repackaging, from the accepted archive cdbaa92f... .
        # Comparing only against the rebuilt archive would be tautological.
        normalized = '\n'.join(x for x in current.splitlines() if x.strip()).encode()
        self.assertEqual(hashlib.sha256(normalized).hexdigest(),
                         '3f34639c899f634c3d84642007bad5aa71c4dd620350c1f9ad520193dad78528')
        self.assertNotIn('# BEGIN operator-selected', current)

    def test_packaged_initializer_matches_source(self):
        for extra in (None, {'dcn-1b-compute-1': [ENTRY]}):
            self.assertEqual(render(extra), render(extra, chart=ROOT/'helm/packages/patched/ovn-2026.1.0.tgz'))

    def test_unsafe_inputs_rejected_at_render(self):
        for key, value in [('bridge', 'br-ex'), ('interface', 'dcn-storage0'), ('vlan', 4095),
                           ('parent', 'eth0;id'), ('physnet', '$(id)'), ('vlan', True)]:
            with self.subTest(key=key, value=value):
                entry = dict(ENTRY, **{key: value})
                render({'dcn-1b-compute-1': [entry]}, expected=1)
        render({'bad;node': [ENTRY]}, expected=1)
        render({'dcn-1b-compute-1': [ENTRY, ENTRY]}, expected=1)

    def run_runtime(self, scenario='', node='dcn-1b-compute-1'):
        script = render({'dcn-1b-compute-1': [ENTRY]})
        start = script.index('# BEGIN operator-selected')
        end = script.index('ovs-vsctl set open . external-ids:ovn-bridge-mappings=', start)
        # The exact rendered optional section plus the real publication line.
        section = script[start:script.index('\n', end)]
        with tempfile.TemporaryDirectory(prefix='ovn-extra-contract-') as directory:
            root = Path(directory)
            fake = root/'tool'
            fake.write_text('''#!/usr/bin/env python3
import json,os,pathlib,sys
root=pathlib.Path(os.environ['TEST_STATE']);path=root/'state.json'
s=json.loads(path.read_text()) if path.exists() else {'ports':{},'owner':{},'writes':[]}
a=sys.argv[1:];scenario=os.environ['TEST_SCENARIO'];name=pathlib.Path(sys.argv[0]).name
if name=='ip':
 if a[:4]==['-d','-o','link','show']:
  if scenario=='missing':sys.exit(1)
  parent='bad-parent' if scenario=='wrong-parent' else 'dcn-storage0'
  vlan=180 if scenario=='wrong-vlan' else 181
  print('9: dcn-nfs-svc@'+parent+': <UP> mtu 1500 vlan protocol 802.1Q id '+str(vlan))
 elif a[:3]==['-o','addr','show']:
  if scenario=='addressed' and a[-1]=='dcn-nfs-svc':print('inet 10.70.30.99/24')
 else:s['writes'].append(['ip']+a)
else:
 a=[x for x in a if not x.startswith('--timeout=')]
 if a[0]=='show':pass
 elif a[0]=='port-to-br':
  if a[1]=='patch-peer':print('br-ex' if scenario=='patch-wrong-bridge' else 'br-int')
  elif scenario=='other-bridge':print('br-ex')
  elif a[1] in s['ports']:print(s['ports'][a[1]])
  else:sys.exit(1)
 elif a[0]=='br-exists':
  if a[1] not in s['owner'] and scenario not in ('unowned','extra-port') and not scenario.startswith('patch-'):sys.exit(2)
 elif a[0]=='get':
  if a[1]=='Bridge':print('"'+s['owner'].get(a[2], 'managed-nfs' if scenario!='unowned' else '')+'"')
  elif a[-1]=='type':print('patch' if scenario.startswith('patch-') else 'system')
  elif a[-1]=='external_ids:ovn-localnet-port':
   print('[]' if scenario=='patch-unmarked' else ('different' if scenario=='patch-mismatched' and a[2]=='patch-peer' else 'provnet-test'))
  elif a[-1]=='options:peer':print('patch-peer' if a[2]=='patch-local' else ('wrong' if scenario=='patch-one-way' else 'patch-local'))
  else:raise RuntimeError(a)
 elif a[0]=='list-ports':
  for port,bridge in s['ports'].items():
   if bridge==a[1]:print(port)
  if scenario=='extra-port':print('unexpected-port')
  if scenario.startswith('patch-'):print('patch-local')
 elif a[:2]==['--may-exist','add-br']:
  s['owner'][a[2]]=a[-1].split('=',1)[1];s['writes'].append(a)
 elif a[:2]==['--may-exist','add-port']:s['ports'][a[3]]=a[2];s['writes'].append(a)
 elif a[:3]==['set','open','.']:s['mapping']=a[3].split('=',1)[1];s['writes'].append(a)
 else:raise RuntimeError(a)
path.write_text(json.dumps(s))
''')
            fake.chmod(0o755)
            for name in ('ip', 'ovs-vsctl'):
                (root/name).symlink_to(fake)
            env = dict(os.environ, PATH=str(root)+':'+os.environ['PATH'], TEST_STATE=str(root), TEST_SCENARIO=scenario, NODE_NAME=node)
            command = 'set -e\nbridge_mappings=external-rack-2:br-ex\n'+section
            results = [subprocess.run(['bash'], input=command, text=True, env=env, capture_output=True) for _ in range(2)]
            state = json.loads((root/'state.json').read_text()) if (root/'state.json').exists() else {}
            return results, state

    def test_repeat_initialization_preserves_both_mappings(self):
        results, state = self.run_runtime()
        self.assertTrue(all(r.returncode == 0 for r in results), [r.stderr for r in results])
        self.assertEqual(state['mapping'], 'external-rack-2:br-ex,managed-nfs:br-nfs')
        self.assertEqual(state['ports'], {'dcn-nfs-svc': 'br-nfs'})

    def test_unselected_gpu_node_has_no_extra_bridge_mutation(self):
        results, state = self.run_runtime(node='dcn-1a-compute-2')
        self.assertTrue(all(r.returncode == 0 for r in results))
        self.assertEqual(state['mapping'], 'external-rack-2:br-ex')
        self.assertEqual(state['ports'], {})
        self.assertTrue(all(w[:3] == ['set', 'open', '.'] for w in state['writes']))

    def test_ovn_localnet_patch_pair_survives_reinitialization(self):
        results, state = self.run_runtime('patch-valid')
        self.assertTrue(all(r.returncode == 0 for r in results), [r.stderr for r in results])
        self.assertEqual(state['mapping'], 'external-rack-2:br-ex,managed-nfs:br-nfs')

    def test_bad_runtime_state_fails_before_writes(self):
        for scenario in ('missing', 'wrong-parent', 'wrong-vlan', 'addressed', 'other-bridge', 'unowned', 'extra-port',
                         'patch-wrong-bridge', 'patch-unmarked', 'patch-mismatched', 'patch-one-way'):
            with self.subTest(scenario=scenario):
                results, state = self.run_runtime(scenario)
                self.assertTrue(all(r.returncode != 0 for r in results))
                self.assertEqual(state.get('writes', []), [])


if __name__ == '__main__':
    unittest.main()
