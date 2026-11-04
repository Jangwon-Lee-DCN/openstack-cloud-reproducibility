"""Render the locked chart, not a reconstructed DaemonSet or chart-source proxy."""
import hashlib
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[2]
IMAGE='quay.io/airshipit/openvswitch@sha256:765eb259920bd4313fc8cb0bb1df7e292764219a4de0c67ad7e80592b4eae7af'


class OpenvswitchArtifactContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lock=yaml.safe_load((ROOT/'release-lock.yaml').read_text())
        releases=lock['spec']['releases']
        entry=next(item for item in releases if item['name']=='openvswitch')
        package=ROOT/entry['package']
        if hashlib.sha256(package.read_bytes()).hexdigest()!=entry['sha256']:
            raise AssertionError('locked package checksum mismatch')
        rendered=subprocess.check_output(['helm','template','openvswitch',str(package),
            '--namespace','openstack','-f',str(ROOT/'deploy/values/site/openvswitch.yaml')],text=True)
        cls.resources=list(yaml.safe_load_all(rendered))
        cls.daemonset=next(r for r in cls.resources if r and r.get('kind')=='DaemonSet')

    def test_values_stage_without_automatic_data_plane_restarts(self):
        self.assertEqual({'type':'OnDelete'},self.daemonset['spec']['updateStrategy'])

    def test_both_main_and_ovs_init_containers_use_the_qualified_digest(self):
        spec=self.daemonset['spec']['template']['spec']
        images={c['name']:c['image'] for c in spec['containers']+spec.get('initContainers',[])}
        for name in ('openvswitch-db','openvswitch-vswitchd','openvswitch-db-perms','openvswitch-vswitchd-modules'):
            self.assertEqual(IMAGE,images[name],name)

    def test_no_host_network_or_data_plane_selector_drift(self):
        spec=self.daemonset['spec']['template']['spec']
        self.assertIs(spec['hostNetwork'],True)
        self.assertEqual('enabled',spec['nodeSelector']['openvswitch'])
        self.assertEqual('/run/openvswitch',next(v for v in spec['volumes']
            if v['name']=='run-openvswitch')['hostPath']['path'])

    def test_existing_network_and_uid_settings_are_retained(self):
        values=yaml.safe_load((ROOT/'deploy/values/site/openvswitch.yaml').read_text())
        self.assertEqual('6640:127.0.0.1',values['conf']['openvswitch_db_server']['ptcp_port'])
        self.assertIsNone(values['conf']['ovs_user_name'])
        self.assertIn('chown 42424:42424',values['conf']['poststart']['extraCommand'])


if __name__=='__main__':unittest.main()
