"""Neutron WSGI request/SQLite acceptance; no production DB, Keystone or OVN.

Run only in the isolated development fixture with the immutable release image.
"""
import importlib.util
import json
import os
import pathlib
import unittest

assert os.environ.get('AI_SPACE_ISOLATED_API') == '1'
from oslo_config import cfg
from oslo_policy import policy as oslo
from neutron import policy
from neutron.conf import policies
from neutron.tests.common import test_db_base_plugin_v2 as db
from neutron.tests.unit.plugins.ml2 import test_plugin as ml2
from neutron_lib import context

s=importlib.util.spec_from_file_location('guard', pathlib.Path(__file__).with_name('renderer.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)


class ProtectedPortAPI(ml2.Ml2PluginV2TestCase):
    def setUp(self):
        cfg.CONF.set_override('extension_drivers',['port_security'],group='ml2')
        super().setUp()

    def setup_config(self):
        # Installed package's source-tree etc/ is absent; no live config files.
        super(db.NeutronDbPluginV2TestCase, self).setup_config(args=[])

    def test_port_lifecycle_authorization(self):
        with self.network() as network:
            with self.subnet(network=network) as subnet:
                network_id=network['network']['id']
                defaults={r.name:str(r.check_str) for r in policies.list_rules()}
                policy._ENFORCER.set_rules(oslo.Rules.from_dict(m.compile_policy(defaults,[network_id])),overwrite=True)
                member=context.Context(user_id='cpu-test-member',project_id=self._project_id,roles=['member','reader'])
                admin=context.get_admin_context()
                body={'port':{'network_id':network_id,'project_id':self._project_id}}
                request=self.new_create_request('ports',body)
                request.environ['neutron.context']=member
                self.assertEqual(403,request.get_response(self.api).status_int)
                request=self.new_create_request('ports',body)
                request.environ['neutron.context']=admin
                response=request.get_response(self.api)
                self.assertEqual(201,response.status_int,response.text)
                port=json.loads(response.text)['port']['id']
                before=self.plugin.get_port(admin,port)
                request=self.new_show_request('ports',port)
                request.environ['neutron.context']=member
                self.assertEqual(200,request.get_response(self.api).status_int)
                for change in [{'name':'renamed'},{'fixed_ips':[]},{'device_owner':'compute:nova'},{'mac_address':'fa:16:3e:00:12:34'},
                               {'security_groups':[]},{'port_security_enabled':False},
                               {'allowed_address_pairs':[{'ip_address':'198.51.100.99'}]},
                               {'binding:vnic_type':'direct'}]:
                    request=self.new_update_request('ports',{'port':change},port)
                    request.environ['neutron.context']=member
                    response=request.get_response(self.api)
                    self.assertEqual(403,response.status_int,response.text)
                    self.assertEqual(before,self.plugin.get_port(admin,port))
                request=self.new_delete_request('ports',port)
                request.environ['neutron.context']=member
                self.assertEqual(403,request.get_response(self.api).status_int)
                self.assertEqual(before,self.plugin.get_port(admin,port))
                request=self.new_delete_request('ports',port)
                request.environ['neutron.context']=admin
                self.assertEqual(204,request.get_response(self.api).status_int)

    def test_ordinary_network_keeps_member_crud(self):
        policy.init()
        defaults={r.name:str(r.check_str) for r in policies.list_rules()}
        policy._ENFORCER.set_rules(oslo.Rules.from_dict(m.compile_policy(defaults,['11111111-1111-4111-8111-111111111111'])),overwrite=True)
        with self.network() as network:
            with self.subnet(network=network):
                member=context.Context(user_id='cpu-test-member',project_id=self._project_id,roles=['member','reader'])
                request=self.new_create_request('ports',{'port':{'network_id':network['network']['id'],'project_id':self._project_id}})
                request.environ['neutron.context']=member
                response=request.get_response(self.api)
                self.assertEqual(201,response.status_int,response.text)
                port=json.loads(response.text)['port']['id']
                request=self.new_update_request('ports',{'port':{'name':'ordinary-user-change'}},port)
                request.environ['neutron.context']=member
                self.assertEqual(200,request.get_response(self.api).status_int)
                request=self.new_delete_request('ports',port)
                request.environ['neutron.context']=member
                self.assertEqual(204,request.get_response(self.api).status_int)


if __name__=='__main__':unittest.main(verbosity=2)
