import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('ovs_ready',ROOT/'deploy/scripts/verify-ovs-artifact-ready.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
IMAGE='quay.io/airshipit/openvswitch@sha256:'+'a'*64


class OvsReadinessTest(unittest.TestCase):
    def setUp(self):
        self.template={'containers':[{'name':n,'image':IMAGE} for n in ('openvswitch-db','openvswitch-vswitchd')],
            'initContainers':[{'name':n,'image':IMAGE} for n in ('openvswitch-db-perms','openvswitch-vswitchd-modules')]}
        self.ds={'metadata':{'uid':'owned','generation':2},'spec':{'template':{'spec':self.template},
            'updateStrategy':{'type':'OnDelete'}},'status':{'observedGeneration':2,
            'desiredNumberScheduled':1,'updatedNumberScheduled':1,'numberReady':1,'numberAvailable':1}}
        self.pod={'metadata':{'ownerReferences':[{'kind':'DaemonSet','uid':'owned','controller':True}]},
            'spec':dict(copy.deepcopy(self.template),nodeName='fixture'),
            'status':{'phase':'Running','conditions':[{'type':'Ready','status':'True'}],
                'containerStatuses':[{'name':n,'imageID':IMAGE,'state':{'running':{}}} for n in module.NAMES]}}

    def test_only_first_install_can_have_no_daemonset(self):
        self.assertTrue(module.validate(None,[],IMAGE,preflight=True))
        with self.assertRaises(ValueError):module.validate(None,[],IMAGE)

    def test_exact_live_artifact_and_ready_updated_nodes_pass(self):
        self.assertTrue(module.validate(self.ds,[self.pod],IMAGE))

    def test_existing_mutable_template_fails_before_helm(self):
        self.template['containers'][0]['image']='quay.io/airshipit/openvswitch:latest-ubuntu_noble'
        with self.assertRaises(ValueError):module.validate(self.ds,[self.pod],IMAGE,preflight=True)

    def test_staging_template_does_not_qualify_old_pod(self):
        self.pod['spec']['containers'][0]['image']='old-tag'
        with self.assertRaises(ValueError):module.validate(self.ds,[self.pod],IMAGE,preflight=True)

    def test_wrong_running_digest_is_not_accepted(self):
        self.pod['status']['containerStatuses'][0]['imageID']='repo@sha256:'+'b'*64
        with self.assertRaises(ValueError):module.validate(self.ds,[self.pod],IMAGE)

    def test_zero_unready_stale_or_wrong_owner_is_not_converged(self):
        for key,value in (('desiredNumberScheduled',0),('observedGeneration',1),
                          ('updatedNumberScheduled',0),('numberReady',0),('numberAvailable',0),('numberMisscheduled',1)):
            ds=copy.deepcopy(self.ds);ds['status'][key]=value
            self.assertFalse(module.validate(ds,[self.pod],IMAGE),key)
        self.pod['metadata']['ownerReferences'][0]['uid']='other'
        self.assertFalse(module.validate(self.ds,[self.pod],IMAGE))

    def test_reconciler_uses_preflight_before_upgrade_and_not_rollout_status(self):
        source=(ROOT/'deploy/scripts/reconcile-full-stack.sh').read_text()
        install=source.split('install_release() {',1)[1]
        self.assertLess(install.index('--preflight'),install.index('helm upgrade'))
        self.assertIn('"$release" == openvswitch && "$kind" == daemonset',source)


if __name__=='__main__':unittest.main()
