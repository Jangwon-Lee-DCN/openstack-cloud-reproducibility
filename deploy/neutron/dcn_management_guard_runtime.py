"""Candidate Neutron configuration adapter, not yet imported by OVNClient.

Empty lists are inert. Production values must opt in exact project IDs and
destinations together; this module neither enrolls projects nor starts workers.
"""
from oslo_config import cfg

import dcn_management_guard as guard


GROUP = 'dcn_management_guard'
cfg.CONF.register_opts([
    cfg.ListOpt('project_ids', default=[], help='Operator-enrolled Keystone project IDs.'),
    cfg.ListOpt('denied_cidrs', default=[], help='Management destination CIDRs denied on enrolled ports.'),
], group=GROUP)


def policy():
    settings = cfg.CONF[GROUP]
    return guard.compile_policy(list(settings.project_ids), list(settings.denied_cidrs))


def enqueue_port(api, transaction, port):
    return guard.enqueue_port(api, transaction, port, policy())


def repair_ports(api, plugin, context):
    """Repair enrolled ports after the normal repair-mode network/LSP sync.

    The caller must not invoke this from log/check-only synchronization. All
    candidates are qualified before opening the single repair transaction.
    """
    desired = policy()
    if not desired:
        return
    from neutron.common.ovn import utils
    candidates = []
    for port in plugin.get_ports(context, filters={'project_id': sorted(desired)}):
        plan = guard.plan_port(port, desired)
        if plan is None or utils.is_lsp_ignored(port):
            continue
        if api.lookup('Logical_Switch_Port', port['id'], default=None) is None:
            raise RuntimeError('Enrolled LSP missing after Neutron port synchronization')
        candidates.append(port)
    with api.transaction(check_error=True) as txn:
        for port in candidates:
            guard.enqueue_port(api, txn, port, desired)
