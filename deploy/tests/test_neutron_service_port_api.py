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
from neutron import manager
from neutron.conf import policies
from neutron.tests.common import test_db_base_plugin_v2 as db
from neutron.tests.common import helpers
from neutron.tests.unit.plugins.ml2 import test_plugin as ml2
from neutron_lib import context
from neutron_lib.callbacks import exceptions as callback_exceptions
from neutron.extensions import securitygroup as sg_exceptions
from dcn_service_port_guard import ManagedPortForbidden, ServicePortGuard

s=importlib.util.spec_from_file_location('guard', pathlib.Path(__file__).with_name('renderer.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)


class ProtectedPortAPI(ml2.Ml2PluginV2TestCase):
    def test_provider_security_group_and_rules_cannot_be_changed_by_member(self):
        admin = context.get_admin_context()
        member = context.Context(user_id='cpu-test-member', project_id=self._project_id,
                                 roles=['member', 'reader'])
        def create_group(name):
            return self.plugin.create_security_group(admin, {'security_group': {
                'name': name, 'description': 'isolated-fixture',
                'tenant_id': self._project_id, 'project_id': self._project_id}})
        protected, ordinary = create_group('protected'), create_group('ordinary')
        def rule(group):
            return {'security_group_rule': {'security_group_id': group['id'],
                'tenant_id': self._project_id, 'project_id': self._project_id,
                'direction': 'ingress', 'ethertype': 'IPv4', 'protocol': 'tcp',
                'port_range_min': 2049, 'port_range_max': 2049,
                'remote_ip_prefix': '192.0.2.0/24', 'remote_group_id': None,
                'remote_address_group_id': None, 'description': ''}}
        existing = self.plugin.create_security_group_rule(admin, rule(protected))
        before = self.plugin.get_security_group(admin, protected['id'])
        ServicePortGuard(['11111111-1111-4111-8111-111111111111'], [protected['id']])
        denied_rule = rule(protected)
        denied_rule['security_group_rule']['port_range_min'] = 22
        denied_rule['security_group_rule']['port_range_max'] = 22
        with self.assertRaises(callback_exceptions.CallbackFailure):
            self.plugin.create_security_group_rule(member, denied_rule)
        with self.assertRaises(callback_exceptions.CallbackFailure):
            self.plugin.delete_security_group_rule(member, existing['id'])
        with self.assertRaises(sg_exceptions.SecurityGroupConflict):
            self.plugin.update_security_group(member, protected['id'],
                                             {'security_group': {'name': 'changed'}})
        with self.assertRaises(sg_exceptions.SecurityGroupInUse):
            self.plugin.delete_security_group(member, protected['id'])
        self.assertEqual(before, self.plugin.get_security_group(admin, protected['id']))
        normal = self.plugin.create_security_group_rule(member, rule(ordinary))
        self.plugin.delete_security_group_rule(member, normal['id'])
        self.plugin.delete_security_group_rule(admin, existing['id'])
        self.plugin.delete_security_group(admin, protected['id'])

    # Exercise actual ML2 binding decisions against an isolated agent record.
    # No OVS agent/process, OVN chassis or Nova VM exists in this fixture.
    _mechanism_drivers = ['openvswitch']

    def setUp(self):
        cfg.CONF.set_override('extension_drivers',['port_security'],group='ml2')
        super().setUp()
        helpers.register_ovs_agent(host='cpu-test-host',plugin=self.plugin)

    def setup_config(self):
        # Installed package's source-tree etc/ is absent; no live config files.
        super(db.NeutronDbPluginV2TestCase, self).setup_config(args=[])

    def test_guard_requires_explicit_networks(self):
        for value in ([], ['not-a-uuid'], ['11111111111141118111111111111111'],
                      ['11111111-1111-4111-8111-111111111111'] * 2):
            with self.assertRaises(ValueError):
                ServicePortGuard(value)

    def test_configured_plugin_loads_through_neutron_loader(self):
        cls = manager.NeutronManager.load_class_for_provider(
            'neutron.service_plugins', 'dcn_service_port_guard.ServicePortGuard')
        self.assertIs(cls, ServicePortGuard)
        cfg.CONF.register_opt(cfg.ListOpt('network_ids', default=[]), group='dcn_service_ports')
        ids = ['11111111-1111-4111-8111-111111111111']
        cfg.CONF.set_override('network_ids', ids, group='dcn_service_ports')
        self.assertEqual(cls().network_ids, frozenset(ids))

    def test_internal_plugin_mutations_are_guarded(self):
        with self.network() as network:
            with self.subnet(network=network) as subnet:
                admin=context.get_admin_context()
                member=context.Context(user_id='cpu-test-member',project_id=self._project_id,roles=['member','reader'])
                with self.port(subnet=subnet) as item:
                    port=item['port']['id']
                    original=self.plugin.get_port(admin,port)
                    ServicePortGuard([network['network']['id']])
                    with self.assertRaises(callback_exceptions.CallbackFailure) as error:
                        self.plugin.update_port(member,port,{'port':{'name':'internal-bypass'}})
                    self.assertTrue(all(isinstance(e,ManagedPortForbidden) for e in error.exception.inner_exceptions))
                    self.assertEqual(original,self.plugin.get_port(admin,port))
                    with self.assertRaises(ManagedPortForbidden):
                        self.plugin.delete_port(member,port)
                    self.assertEqual(original,self.plugin.get_port(admin,port))

    def test_port_lifecycle_authorization(self):
        with self.network() as network:
            with self.subnet(network=network) as subnet:
                network_id=network['network']['id']
                defaults={r.name:str(r.check_str) for r in policies.list_rules()}
                policy._ENFORCER.set_rules(oslo.Rules.from_dict(m.compile_policy(defaults,[network_id])),overwrite=True)
                ServicePortGuard([network_id])
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
                # Nova uses its privileged Neutron client to bind/unbind a
                # pre-created port. Exercise those request fields without
                # pretending the ML2 test driver is a live Nova/OVN binding.
                server_id='33333333-3333-4333-8333-333333333333'
                for changes in [
                    {'device_id':server_id,'device_owner':'compute:rack-2','binding:host_id':'cpu-test-host'},
                    {'device_id':'','device_owner':'','binding:host_id':''},
                ]:
                    request=self.new_update_request('ports',{'port':changes},port)
                    request.environ['neutron.context']=admin
                    response=request.get_response(self.api)
                    self.assertEqual(200,response.status_int,response.text)
                    result=json.loads(response.text)['port']
                    # A successful policy decision is not a successful bind.
                    # Never let HTTP 200 conceal an ML2 binding failure.
                    self.assertEqual('ovs' if changes['device_id'] else 'unbound',result.get('binding:vif_type'),response.text)
                    self.assertEqual(changes['binding:host_id'],result['binding:host_id'])
                    after=self.plugin.get_port(admin,port)
                    self.assertEqual(changes['device_id'],after['device_id'])
                    self.assertEqual(changes['device_owner'],after['device_owner'])
                    self.assertEqual(before['fixed_ips'],after['fixed_ips'])
                    self.assertEqual(before['mac_address'],after['mac_address'])
                self.assertEqual(port,self.plugin.get_port(admin,port)['id'])
                request=self.new_delete_request('ports',port)
                request.environ['neutron.context']=admin
                self.assertEqual(204,request.get_response(self.api).status_int)

    def test_ordinary_network_keeps_member_crud(self):
        policy.init()
        defaults={r.name:str(r.check_str) for r in policies.list_rules()}
        policy._ENFORCER.set_rules(oslo.Rules.from_dict(m.compile_policy(defaults,['11111111-1111-4111-8111-111111111111'])),overwrite=True)
        ServicePortGuard(['11111111-1111-4111-8111-111111111111'])
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

    def test_member_cannot_attach_protected_port_to_router(self):
        """A separate router endpoint must not bypass protected port writes."""
        with self.network() as network:
            with self.subnet(network=network):
                defaults={r.name:str(r.check_str) for r in policies.list_rules()}
                policy._ENFORCER.set_rules(oslo.Rules.from_dict(m.compile_policy(defaults,[network['network']['id']])),overwrite=True)
                ServicePortGuard([network['network']['id']])
                member=context.Context(user_id='cpu-test-member',project_id=self._project_id,roles=['member','reader'])
                admin=context.get_admin_context()
                request=self.new_create_request('ports',{'port':{'network_id':network['network']['id'],'project_id':self._project_id}})
                request.environ['neutron.context']=admin
                response=request.get_response(self.api)
                self.assertEqual(201,response.status_int,response.text)
                port=json.loads(response.text)['port']['id']
                before=self.plugin.get_port(admin,port)
                request=self.new_create_request('routers',{'router':{'name':'isolation-test','project_id':self._project_id,'admin_state_up':True}})
                request.environ['neutron.context']=member
                response=request.get_response(self.api)
                self.assertEqual(201,response.status_int,response.text)
                router=json.loads(response.text)['router']['id']
                before_ports=self.plugin.get_ports(admin)
                for target in [{'port_id':port},{'subnet_id':before['fixed_ips'][0]['subnet_id']}]:
                    request=self.new_action_request('routers',target,router,'add_router_interface')
                    request.environ['neutron.context']=member
                    response=request.get_response(self.api)
                    self.assertEqual(403,response.status_int,response.text)
                    self.assertEqual(before,self.plugin.get_port(admin,port))
                    self.assertEqual(before_ports,self.plugin.get_ports(admin))

    def test_provider_security_group_cannot_be_widened_by_member(self):
        policy.init()
        admin=context.get_admin_context()
        member=context.Context(user_id='cpu-test-member',project_id=self._project_id,roles=['member','reader'])

        def send(request, identity):
            request.environ['neutron.context']=identity
            return request.get_response(self.api)

        response=send(self.new_create_request('security-groups',{'security_group':{
            'name':'provider-nfs-only','description':'isolated fixture',
            'project_id':'22222222-2222-4222-8222-222222222222'}}),admin)
        self.assertEqual(201,response.status_int,response.text)
        group=json.loads(response.text)['security_group']
        group_id=group['id']
        for rule in group['security_group_rules']:
            response=send(self.new_delete_request('security-group-rules',rule['id']),admin)
            self.assertEqual(204,response.status_int,response.text)
        response=send(self.new_create_request('security-group-rules',{'security_group_rule':{
            'project_id':'22222222-2222-4222-8222-222222222222',
            'security_group_id':group_id,'direction':'egress','ethertype':'IPv4',
            'protocol':'tcp','port_range_min':2049,'port_range_max':2049,
            'remote_ip_prefix':'198.51.100.10/32'}}),admin)
        self.assertEqual(201,response.status_int,response.text)
        before=self.plugin.get_security_group(admin,group_id)
        self.assertEqual(1,len(before['security_group_rules']))
        with self.network() as network:
            with self.subnet(network=network):
                response=send(self.new_create_request('ports',{'port':{
                    'network_id':network['network']['id'],'project_id':self._project_id,
                    'security_groups':[group_id]}}),admin)
                self.assertEqual(201,response.status_int,response.text)
                self.assertEqual([group_id],json.loads(response.text)['port']['security_groups'])
                attempts=[
                    self.new_create_request('security-group-rules',{'security_group_rule':{
                        'security_group_id':group_id,'direction':'egress',
                        'ethertype':'IPv4','remote_ip_prefix':'0.0.0.0/0'}}),
                    self.new_delete_request('security-group-rules',before['security_group_rules'][0]['id']),
                    self.new_update_request('security-groups',{'security_group':{'name':'hijacked'}},group_id),
                    self.new_delete_request('security-groups',group_id),
                ]
                for request in attempts:
                    response=send(request,member)
                    self.assertIn(response.status_int,(403,404),response.text)
                    self.assertEqual(before,self.plugin.get_security_group(admin,group_id))


if __name__=='__main__':unittest.main(verbosity=2)
