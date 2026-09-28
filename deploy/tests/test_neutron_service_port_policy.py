import importlib.util
import pathlib
import unittest

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


if __name__ == '__main__': unittest.main()
