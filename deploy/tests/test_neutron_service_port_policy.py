import importlib.util
import base64
import configparser
import json
import pathlib
import subprocess
import unittest

import yaml

s = importlib.util.spec_from_file_location('guard', pathlib.Path(__file__).parents[1]/'scripts/render-neutron-service-port-policy.py')
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
NETWORK = '11111111-1111-4111-8111-111111111111'


class GuardTests(unittest.TestCase):
    def base(self):
        return dict(create_port='role:member', update_port='role:member', delete_port='role:member', get_port='role:reader')

    def test_additive_and_preserves_read_rule(self):
        base = self.base(); out = m.compile_policy(base, [NETWORK])
        self.assertEqual(out['get_port'], base['get_port'])
        for op in m.OPERATIONS:
            self.assertEqual(out[m.PREFIX+'original_'+op], base[op])
            self.assertIn(' and ', out[op])
        self.assertEqual(base, self.base())

    def test_missing_defaults_rejected(self):
        with self.assertRaises(ValueError): m.compile_policy({}, [NETWORK])

    def test_invalid_scope_rejected(self):
        for ids in [[], [NETWORK, NETWORK], ['*'], ['x or role:member']]:
            with self.assertRaises(ValueError): m.compile_policy(self.base(), ids)

    def test_no_repeated_wrap(self):
        out = m.compile_policy(self.base(), [NETWORK])
        with self.assertRaises(ValueError): m.compile_policy(out, [NETWORK])

    def test_unknown_target_is_not_unprotected_default(self):
        out=m.compile_policy(self.base(), [NETWORK])
        self.assertTrue(out[m.PREFIX+'guard'].startswith('(field:port:network_id='))

    def test_values_preserve_service_plugins_and_select_exact_networks(self):
        plugins = ['ovn-router', 'firewall_v2', 'log']
        result = m.compile_values(self.base(), [NETWORK], plugins)['conf']
        self.assertEqual(result['neutron']['DEFAULT']['service_plugins'],
                         'ovn-router,firewall_v2,log,'+m.PLUGIN)
        self.assertEqual(result['neutron']['dcn_service_ports']['network_ids'], NETWORK)
        self.assertEqual(result['policy']['get_port'], 'role:reader')
        self.assertEqual(plugins, ['ovn-router', 'firewall_v2', 'log'])

    def test_ambiguous_or_repeated_plugin_config_is_rejected(self):
        for plugins in ([], '', ['ovn-router,log'], ['log', 'log'], [' log'], [m.PLUGIN]):
            with self.subTest(plugins=plugins), self.assertRaises(ValueError):
                m.compile_values(self.base(), [NETWORK], plugins)

    def test_explicit_security_groups_and_invalid_scope(self):
        result = m.compile_values(self.base(), [NETWORK], ['ovn-router'], [NETWORK])
        self.assertEqual(result['conf']['neutron']['dcn_service_ports']['security_group_ids'], NETWORK)
        for groups in ([NETWORK, NETWORK], ['*'], ['not-a-uuid']):
            with self.assertRaises(ValueError):
                m.compile_values(self.base(), [NETWORK], ['ovn-router'], groups)

    def test_packaged_chart_renders_complete_candidate_configuration(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        values = m.compile_values(self.base(), [NETWORK], ['ovn-router', 'firewall_v2', 'log'], [NETWORK])
        result = subprocess.run(['helm', 'template', 'neutron',
            str(root/'helm/packages/patched/neutron-2026.1.0.tgz'),
            '-f', str(root/'deploy/values/site/neutron.yaml'),
            '--set-json', 'conf='+json.dumps(values['conf'])],
            capture_output=True, text=True, check=True)
        config = next(d for d in yaml.safe_load_all(result.stdout)
                      if d and 'neutron.conf' in d.get('data', {}))
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(base64.b64decode(config['data']['neutron.conf']).decode())
        self.assertEqual(parser['DEFAULT']['service_plugins'], 'ovn-router,firewall_v2,log,'+m.PLUGIN)
        self.assertEqual(parser['dcn_service_ports']['network_ids'], NETWORK)
        self.assertEqual(parser['dcn_service_ports']['security_group_ids'], NETWORK)
        policy = yaml.safe_load(base64.b64decode(config['data']['policy.yaml']))
        self.assertEqual(policy['get_port'], 'role:reader')
        self.assertEqual(policy['update_port'], values['conf']['policy']['update_port'])


if __name__ == '__main__': unittest.main()
