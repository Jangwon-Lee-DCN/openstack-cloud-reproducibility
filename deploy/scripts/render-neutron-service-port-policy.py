#!/usr/bin/env python3
"""Compile an additive service-network port guard. Does not deploy anything.

Input effective_rules must contain the actual release's resolved default plus
override rules. Output is a full policy mapping, not a replacement for collecting
the release defaults. Protected network IDs are operator inputs, never tags.
"""
import argparse
import json
import uuid

OPERATIONS = ('create_port', 'update_port', 'delete_port')
PREFIX = 'dcn_service_port_'
PLUGIN = 'dcn_service_port_guard.ServicePortGuard'


def compile_policy(effective_rules, network_ids):
    if not isinstance(effective_rules, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in effective_rules.items()):
        raise ValueError('Expected resolved string policy mapping')
    if any(k.startswith(PREFIX) for k in effective_rules):
        raise ValueError('Already guarded policy must not be wrapped again')
    if not network_ids or len(network_ids) != len(set(network_ids)):
        raise ValueError('Explicit nonempty unique service network IDs required')
    for value in network_ids:
        if str(uuid.UUID(value)) != value:
            raise ValueError('Canonical network UUID required')
    if any(k not in effective_rules for k in OPERATIONS):
        raise ValueError('Missing effective operation rule; refusing guessed default')
    result = dict(effective_rules)
    result[PREFIX+'network'] = ' or '.join(
        'field:port:network_id='+value for value in sorted(network_ids))
    # Neutron builds a full target from the existing resource for update/delete.
    # Fail closed if a future API path omits this immutable selector. Actual
    # HTTP tests must qualify target construction before production rollout.
    result[PREFIX+'guard'] = (
        '(field:port:network_id=~^[0-9a-f-]{36}$) and '
        '(not rule:'+PREFIX+'network or role:admin or role:service)')
    for operation in OPERATIONS:
        original = PREFIX+'original_'+operation
        result[original] = effective_rules[operation]
        result[operation] = 'rule:'+original+' and rule:'+PREFIX+'guard'
    return result


def compile_values(effective_rules, network_ids, existing_plugins, security_group_ids=()):
    """Produce an explicit candidate override, never silently enable a plugin."""
    policy = compile_policy(effective_rules, network_ids)
    if (not isinstance(existing_plugins, list) or not existing_plugins
            or not all(isinstance(p, str) and p and p.strip() == p and ',' not in p
                       for p in existing_plugins)
            or len(set(existing_plugins)) != len(existing_plugins)):
        raise ValueError('Explicit unique current service plugins required')
    if PLUGIN in existing_plugins:
        raise ValueError('Already guarded service plugin configuration')
    if (not isinstance(security_group_ids, (list, tuple))
            or len(set(security_group_ids)) != len(security_group_ids)
            or any(str(uuid.UUID(value)) != value for value in security_group_ids)):
        raise ValueError('Explicit canonical unique security-group UUIDs required')
    return {'conf': {'policy': policy, 'neutron': {
        'DEFAULT': {'service_plugins': ','.join(existing_plugins+[PLUGIN])},
        'dcn_service_ports': {'network_ids': ','.join(sorted(network_ids)),
                             'security_group_ids': ','.join(sorted(security_group_ids))}}}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('effective_rules')
    parser.add_argument('--network-id', action='append', required=True)
    parser.add_argument('--security-group-id', action='append', default=[])
    parser.add_argument('--service-plugin', action='append',
                        help='Emit Helm values; repeat for every existing service plugin')
    args = parser.parse_args()
    with open(args.effective_rules) as f:
        rules = json.load(f)
    if args.security_group_id and args.service_plugin is None:
        parser.error('Security-group protection requires service-plugin values')
    result = (compile_values(rules, args.network_id, args.service_plugin, args.security_group_id)
              if args.service_plugin is not None else compile_policy(rules, args.network_id))
    print(json.dumps(result, indent=2, sort_keys=True))
