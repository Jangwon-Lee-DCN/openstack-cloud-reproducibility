import hashlib
import base64
import copy
import importlib.util
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'array_ca', Path(__file__).resolve().parents[1] / 'scripts/render-manila-array-ca.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ArrayCATests(unittest.TestCase):
    def test_render_only_rejects_other_releases_builds_and_invalid_modes(self):
        script = Path(__file__).resolve().parents[1]/'scripts/reconcile-full-stack.sh'
        for mode, release, build in [('1', 'nova', '0'), ('1', 'manila', '1'), ('yes', 'manila', '0')]:
            environment = dict(os.environ, MANILA_RENDER_ONLY=mode,
                               ONLY_RELEASE=release, BUILD_IMAGES=build)
            result = subprocess.run(['bash', str(script)], env=environment,
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(result.stdout)

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / 'ca.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                            '-keyout', str(Path(directory) / 'key.pem'), '-out', str(cert),
                            '-days', '1', '-subj', '/CN=fixture-only',
                            '-addext', 'basicConstraints=critical,CA:TRUE'],
                           check=True, capture_output=True, timeout=30)
            cls.pem = cert.read_text()
        cls.digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cls.pem)).hexdigest()

    def test_scoped_verified_mount(self):
        values = module.render(self.pem, self.digest)
        self.assertNotIn('conf', values)
        self.assertIn('dell_ssl_cert_verify = true', values['extraObjects'][0]['data']['99-powerstore-trust.conf'])
        self.assertTrue(values['extraObjects'][0]['immutable'])
        mounts = values['pod']['mounts']
        self.assertEqual(list(mounts), ['manila_share'])
        self.assertTrue(mounts['manila_share']['manila_share']['volumeMounts'][0]['readOnly'])

    def test_rendered_trust_requires_config_certificate_and_consumer(self):
        values = module.render(self.pem, self.digest)
        mount = values['pod']['mounts']['manila_share']['manila_share']
        config = '[powerstore]\ndell_ssl_cert_verify=true\ndell_ssl_cert_path=/etc/manila/array-ca/ca.pem\n'
        objects = [values['extraObjects'][0],
            {'kind': 'Secret', 'metadata': {'name': 'manila-etc'},
             'data': {'manila.conf': base64.b64encode(config.encode()).decode()}},
            {'kind': 'Deployment', 'metadata': {'name': 'manila-share'}, 'spec': {'replicas': 1,
                'strategy': {'type': 'Recreate'}, 'template': {
                'spec': {'volumes': mount['volumes'] + [{'name': 'manila-etc-snippets',
                    'projected': {'sources': values['pod']['etcSources']['manila_share']}}], 'containers': [
                    {'name': 'manila-share', 'volumeMounts': mount['volumeMounts'] + [
                        {'name': 'manila-etc-snippets', 'mountPath': '/etc/manila/manila.conf.d/', 'readOnly': True}]}]}}}}]
        module.verify_rendered(objects, self.pem, self.digest)
        # A nested mount under a read-only parent cannot rely on runc creating
        # its mountpoint, regardless of the parent's volume backing type.
        readonly_parent = copy.deepcopy(objects)
        pod = readonly_parent[2]['spec']['template']['spec']
        pod['volumes'].append({'name': 'readonly-parent', 'emptyDir': {}})
        pod['containers'][0]['volumeMounts'].insert(0, {
            'name': 'readonly-parent', 'mountPath': '/etc/manila/',
            'readOnly': True})
        with self.assertRaisesRegex(ValueError, 'read-only parent'):
            module.verify_rendered(readonly_parent, self.pem, self.digest)
        for mutate in (
                lambda o: o[0].update(immutable=False),
                lambda o: o[2]['spec'].update(strategy={'type': 'RollingUpdate'}),
                lambda o: o[0]['data'].update({'99-powerstore-trust.conf': '[powerstore]\ndell_ssl_cert_verify=false\n'}),
                lambda o: o[2]['spec']['template']['spec']['containers'][0]['volumeMounts'][0].update(readOnly=False),
                lambda o: o.append(copy.deepcopy(o[0])),
                lambda o: o.pop()):
            bad = copy.deepcopy(objects)
            mutate(bad)
            with self.assertRaises(ValueError):
                module.verify_rendered(bad, self.pem, self.digest)

    def test_reject_unapproved_or_multiple_certificates(self):
        for pem, digest in ((self.pem, '0' * 64), (self.pem, ''),
                            (self.pem + self.pem, self.digest), ('invalid', self.digest)):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                module.render(pem, digest)

    def test_preserves_base_and_replay_is_idempotent(self):
        base = {'extraObjects': [{'kind': 'ConfigMap', 'metadata': {'name': 'existing'}}],
                'pod': {'mounts': {'manila_share': {'host_openvswitch': False,
                    'manila_share': {'volumes': [{'name': 'existing', 'emptyDir': {}}]}}}},
                'conf': {'manila': {'powerstore': {'dell_nas_login': 'fixture-only'}}}}
        result = module.render(self.pem, self.digest, base)
        self.assertEqual(len(base['extraObjects']), 1)
        self.assertEqual(len(result['extraObjects']), 2)
        self.assertEqual(len(result['pod']['mounts']['manila_share']['manila_share']['volumes']), 2)
        self.assertFalse(result['pod']['mounts']['manila_share']['host_openvswitch'])
        self.assertEqual(result['conf']['manila']['powerstore']['dell_nas_login'], 'fixture-only')
        self.assertEqual(module.render(self.pem, self.digest, result), result)

    def test_conflicting_mount_rejected(self):
        result = module.render(self.pem, self.digest)
        result['pod']['mounts']['manila_share']['manila_share']['volumeMounts'][0]['readOnly'] = False
        with self.assertRaises(ValueError):
            module.render(self.pem, self.digest, result)

    def test_ordered_values_match_list_replacement_and_mapping_merge(self):
        first = {'extraObjects': [{'metadata': {'name': 'old'}}],
                 'conf': {'manila': {'powerstore': {'dell_nas_login': 'fixture'}}}}
        second = {'extraObjects': [{'metadata': {'name': 'new'}}],
                  'conf': {'manila': {'powerstore': {'dell_ssl_cert_verify': False}}}}
        combined = module.merge_values(first, second)
        result = module.render(self.pem, self.digest, combined)
        self.assertEqual(result['extraObjects'][0]['metadata']['name'], 'new')
        self.assertEqual(len(result['extraObjects']), 2)
        self.assertEqual(result['conf']['manila']['powerstore']['dell_nas_login'], 'fixture')
        self.assertEqual(result['conf'], combined['conf'])
        self.assertIn('dell_ssl_cert_verify = true', result['extraObjects'][-1]['data']['99-powerstore-trust.conf'])


if __name__ == '__main__':
    unittest.main()
