import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('share_post_render',
    Path(__file__).parents[1]/'scripts/post-render-manila-share.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ShareRenderTests(unittest.TestCase):
    def setUp(self):
        self.objects = [None, {'kind': 'Secret', 'data': {'fixture': 'unchanged'}},
            {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': 'manila-share'},
             'spec': {'replicas': 1, 'strategy': {'type': 'RollingUpdate',
                 'rollingUpdate': {'maxSurge': 3}}, 'template': {'fixture': 'preserved'}}},
            {'kind': 'Deployment', 'metadata': {'name': 'manila-api'},
             'spec': {'strategy': {'type': 'RollingUpdate'}}}]

    def test_only_share_strategy_changes_and_replay_is_stable(self):
        original = copy.deepcopy(self.objects)
        expected = copy.deepcopy(original)
        expected[2]['spec']['strategy'] = {'type': 'Recreate'}
        result = m.render(self.objects)
        self.assertEqual(self.objects, original)
        self.assertEqual(result, expected)
        self.assertEqual(m.render(result), expected)

    def test_missing_duplicate_or_multi_manager_refused(self):
        for objects in (self.objects[:2], self.objects+[self.objects[2]]):
            with self.assertRaises(ValueError):
                m.render(objects)
        self.objects[2]['spec']['replicas'] = 2
        with self.assertRaises(ValueError):
            m.render(self.objects)
