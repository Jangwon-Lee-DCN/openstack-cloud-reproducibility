import copy
import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/verify-vpc-alert-contract.py'
SPEC=importlib.util.spec_from_file_location('vpc_alert_contract',SCRIPT)
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class VPCAlertContractTest(unittest.TestCase):
    def setUp(self):
        self.expected={'spec':{'groups':[{'rules':[
            {'alert':name,'expr':'authoritative fixture expression','for':'5m',
             'labels':{'severity':'warning'},'annotations':{'summary':'fixture summary'}}
            for name in MODULE.ALERTS]}]}}
        self.live=copy.deepcopy(self.expected)

    def test_exact_authority_is_accepted_without_reimplementing_its_promql(self):
        MODULE.assert_alerts(self.live,self.expected)

    def test_a_different_capacity_expression_is_not_accepted(self):
        self.live['spec']['groups'][0]['rules'][0]['expr']='outdated or incorrect expression'
        with self.assertRaisesRegex(ValueError,'expr'):MODULE.assert_alerts(self.live,self.expected)

    def test_drift_in_duration_severity_or_annotation_is_rejected(self):
        for key,value in (('for','1s'),('labels',{'severity':'none'}),('annotations',{'summary':'other'})):
            live=copy.deepcopy(self.live)
            live['spec']['groups'][0]['rules'][1][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,key):
                MODULE.assert_alerts(live,self.expected)

    def test_missing_required_alert_is_not_a_pass(self):
        self.live['spec']['groups'][0]['rules'].pop()
        with self.assertRaisesRegex(ValueError,'missing'):MODULE.assert_alerts(self.live,self.expected)

    def test_duplicate_alert_definitions_are_ambiguous_not_a_pass(self):
        self.live['spec']['groups'][0]['rules'].append(copy.deepcopy(self.live['spec']['groups'][0]['rules'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate'):MODULE.assert_alerts(self.live,self.expected)
