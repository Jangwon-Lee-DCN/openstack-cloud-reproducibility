import unittest

from dcn_loki_gateway.policy import project_selector


PROJECT = "1234567890abcdef1234567890abcdef"


class PolicyTest(unittest.TestCase):
    def test_injects_project_matcher(self):
        self.assertEqual(
            project_selector('{job="nova"} |= "error"', PROJECT),
            '{openstack_project_id="1234567890abcdef1234567890abcdef",job="nova"} |= "error"',
        )

    def test_overwrites_caller_project_matcher(self):
        secured = project_selector('{openstack_project_id="victim",job="neutron"}', PROJECT)
        self.assertNotIn("victim", secured)
        self.assertEqual(1, secured.count("openstack_project_id"))

    def test_rejects_selector_free_query(self):
        with self.assertRaisesRegex(ValueError, "selector"):
            project_selector("sum(rate(foo[5m]))", PROJECT)

    def test_rejects_invalid_project_identifier(self):
        with self.assertRaisesRegex(ValueError, "project id"):
            project_selector('{job="nova"}', "../../admin")
