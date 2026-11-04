import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'automation/ansible/roles/cluster_baseline/files/reconcile_gateway_labels.py'
spec=importlib.util.spec_from_file_location('gateway_labels',SOURCE)
gateway=importlib.util.module_from_spec(spec);spec.loader.exec_module(gateway)


class GatewayLabelTests(unittest.TestCase):
    def setUp(self):
        self.roles={'compute-gpu':['compute','gpu'],'gateway-a':['compute','ovn_gateway']}
        self.labels={'openstack-network-gateway':'enabled','openstack-ovn-gateway':'enabled',
            'openstack-network-node':'enabled','openvswitch':'enabled','openstack-compute-node':'enabled',
            'openstack-gpu':'enabled','l3-agent':'enabled','maintenance':'keep'}
        self.nodes={'kind':'List','items':[
            {'kind':'Node','metadata':{'name':name,'uid':name+'-uid','resourceVersion':'10',
                                     'labels':copy.deepcopy(self.labels)}} for name in self.roles]}

    def test_only_gateway_aliases_withdrawn_and_other_labels_unchanged(self):
        before=copy.deepcopy(self.nodes)
        result=gateway.plan(self.roles,self.nodes)
        self.assertEqual(self.nodes,before);self.assertEqual(len(result),1)
        self.assertEqual(result[0]['node'],'compute-gpu')
        self.assertEqual(result[0]['patch'][:2],[{'op':'test','path':'/metadata/uid','value':'compute-gpu-uid'},
            {'op':'test','path':'/metadata/resourceVersion','value':'10'}])
        self.assertEqual([v['path'] for v in result[0]['patch'] if v['op']=='remove'],
            ['/metadata/labels/openstack-network-gateway','/metadata/labels/openstack-ovn-gateway'])

    def test_positive_roles_not_gpu_type_or_bgp_flags_decide_eligibility(self):
        self.roles['compute-gpu'].append('ovn_gateway')
        self.assertEqual(gateway.plan(self.roles,self.nodes),[])
        self.nodes['items'][0]['metadata']['labels']={}
        result=gateway.plan(self.roles,self.nodes)
        self.assertTrue(result[0]['desired_gateway'])
        self.assertEqual([v['value'] for v in result[0]['patch'] if v['op']=='add'],['enabled','enabled'])

    def test_fresh_missing_labels_object_is_explicitly_created(self):
        del self.nodes['items'][1]['metadata']['labels']
        result=gateway.plan(self.roles,self.nodes)
        positive=next(v for v in result if v['node']=='gateway-a')
        self.assertEqual(positive['patch'][2],{'op':'add','path':'/metadata/labels','value':{}})

    def test_idempotence_and_node_list_printing(self):
        for label in gateway.LABELS:self.nodes['items'][0]['metadata']['labels'].pop(label)
        self.assertEqual(gateway.plan(self.roles,self.nodes),[])
        self.nodes['kind']='NodeList';self.assertEqual(gateway.plan(self.roles,self.nodes),[])

    def test_unknown_inventory_fails_before_api_reads(self):
        for roles in ({},{'node':None},{'node':[]},{'node':['compute','compute']},
                      {'node':'compute'},{'node;shutdown':['compute']}):
            with self.subTest(roles=roles),self.assertRaises(ValueError):gateway.require_roles(roles)

    def test_missing_ambiguous_or_unversioned_nodes_rejected(self):
        variants=[]
        v=copy.deepcopy(self.nodes);v['items'].pop();variants.append(v)
        v=copy.deepcopy(self.nodes);v['items'].append(copy.deepcopy(v['items'][0]));variants.append(v)
        for key in ('uid','resourceVersion'):
            v=copy.deepcopy(self.nodes);del v['items'][0]['metadata'][key];variants.append(v)
        v=copy.deepcopy(self.nodes);v['items'][0]['metadata']['labels'][gateway.LABELS[0]]='custom';variants.append(v)
        for value in variants:
            with self.assertRaises(ValueError):gateway.plan(self.roles,value)

    def test_check_uses_real_server_dry_run_only(self):
        calls=[]
        def kube(*args):
            calls.append(args)
            return copy.deepcopy(self.nodes) if args[0]=='get' else copy.deepcopy(self.nodes['items'][0])
        with patch.object(gateway,'kube',side_effect=kube),patch('sys.argv',
                ['reconcile','--roles-json',json.dumps(self.roles),'--check']),patch('sys.stdout',new_callable=io.StringIO) as output:
            gateway.main();value=json.loads(output.getvalue())
        self.assertTrue(value['check_mode']);self.assertTrue(value['changed'])
        self.assertFalse(value['runtime_cms_reconciled'])
        self.assertIn('--dry-run=server',calls[1]);self.assertEqual(len(calls),2)

    def test_apply_rechecks_roles_after_patches(self):
        calls=[];current=copy.deepcopy(self.nodes)
        def kube(*args):
            calls.append(args)
            if args[0]=='get':return copy.deepcopy(current)
            self.assertNotIn('--dry-run=server',args)
            for label in gateway.LABELS:current['items'][0]['metadata']['labels'].pop(label)
            return copy.deepcopy(current['items'][0])
        with patch.object(gateway,'kube',side_effect=kube),patch('sys.argv',
                ['reconcile','--roles-json',json.dumps(self.roles),'--apply']),patch('sys.stdout',new_callable=io.StringIO):
            gateway.main()
        self.assertEqual([v[0] for v in calls],['get','patch','get'])

    def test_rebuild_keeps_compute_data_plane_and_removes_stale_alias_acceptance(self):
        source=(ROOT/'automation/ansible/roles/cluster_baseline/tasks/main.yml').read_text()
        compute=source.split('- name: Apply canonical Nova and OVS labels to compute nodes',1)[1].split('- name:',1)[0]
        self.assertIn('openstack-network-node=enabled',compute)
        self.assertIn('reconcile_gateway_labels.py',source)
        verifier=(ROOT/'automation/ansible/playbooks/32-verify-node-contract.yml').read_text()
        for label in gateway.LABELS:self.assertIn("'"+label+"' not in live_node.metadata.labels",verifier)

    def test_full_rebuild_verifies_roles_before_provider_or_service_installation(self):
        site=(ROOT/'automation/ansible/playbooks/site.yml').read_text()
        self.assertLess(site.index('30-cluster-baseline.yml'),site.index('32-verify-node-contract.yml'))
        self.assertLess(site.index('32-verify-node-contract.yml'),site.index('35-provider-uplinks.yml'))


if __name__=='__main__':unittest.main()
