"""Run with the release's installed neutron/oslo-policy, never mutates service.

Import verify and supply compile_policy from the sibling policy renderer.
This is policy-engine acceptance, not native HTTP or Nova lifecycle coverage.
"""


def verify(compile_policy):
    from oslo_config import cfg
    from oslo_policy import policy as oslo
    from neutron import policy as registration  # noqa: F401; registers FieldCheck
    from neutron.conf import policies

    defaults = list(policies.list_rules())
    base = {r.name: str(r.check_str) for r in defaults}
    service = '11111111-1111-4111-8111-111111111111'
    ordinary = '22222222-2222-4222-8222-222222222222'
    guarded = compile_policy(base, [service])

    def engine(rules):
        e = oslo.Enforcer(cfg.ConfigOpts(), use_conf=False)
        e.register_defaults(defaults)
        e.set_rules(oslo.Rules.from_dict(rules), overwrite=True)
        return e

    old, new = engine(base), engine(guarded)
    project = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    count = 0
    for operation in ('create_port', 'update_port', 'delete_port'):
        for role in ('reader', 'member', 'admin', 'service'):
            credentials = {'roles': [role], 'project_id': project,
                           'is_admin': role == 'admin'}
            for network in (service, ordinary):
                target = {'network_id': network, 'project_id': project,
                          'tenant_id': project, 'network:project_id': project,
                          'device_owner': 'compute:nova'}
                before = old.enforce(operation, target, credentials)
                after = new.enforce(operation, target, credentials)
                if network == ordinary or role in ('admin', 'service'):
                    assert before == after, (operation, role, 'regression')
                else:
                    assert not after, (operation, role, 'protected bypass')
                count += 1
            assert not new.enforce(operation, {'project_id': project}, credentials)
    return {'policy_cases': count, 'missing_target_cases': 12,
            'http_acceptance': 'not performed', 'nova_lifecycle': 'not performed'}
