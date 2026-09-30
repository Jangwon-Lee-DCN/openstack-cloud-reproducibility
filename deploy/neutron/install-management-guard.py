"""Strict build-time hooks for candidate mandatory management-egress policy.

No fuzzy patching: upstream method/anchor drift fails the image build. This
installer does not enable policy; runtime defaults remain empty and inert.
"""
import argparse
import ast
from pathlib import Path

IMPORT = 'import dcn_management_guard_runtime as management_guard\n'
ANCHOR = 'from neutron.common.ovn import constants as ovn_const\n'


def method_replace(source, class_name, method_name, old, new):
    tree = ast.parse(source)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name]
    if len(classes) != 1:
        raise ValueError('Expected unique '+class_name)
    methods = [n for n in classes[0].body if isinstance(n, ast.FunctionDef) and n.name == method_name]
    if len(methods) != 1:
        raise ValueError('Expected unique '+method_name)
    method = methods[0]
    lines = source.splitlines(keepends=True)
    body = ''.join(lines[method.lineno-1:method.end_lineno])
    if body.count(old) != 1:
        raise ValueError('Unsupported upstream hook shape: '+method_name)
    lines[method.lineno-1:method.end_lineno] = [body.replace(old, new)]
    return ''.join(lines)


def transform(source, kind):
    if IMPORT in source:
        raise ValueError('Already patched source requires a fresh immutable base')
    if source.count(ANCHOR) != 1:
        raise ValueError('Upstream import anchor drift')
    source = source.replace(ANCHOR, ANCHOR+IMPORT)
    if kind == 'client':
        for method, call in [('create_port', 'self._qos_driver.create_port(context, txn, port, port_cmd)'),
                             ('update_port', 'self._qos_driver.update_port(context, txn, port, port_object)')]:
            old = '            '+call+'\n'
            source = method_replace(source, 'OVNClient', method, old,
                '            management_guard.enqueue_port(self._nb_idl, txn, port)\n'+old)
    elif kind == 'sync':
        old = '        self.sync_networks_ports_and_dhcp_opts(ctx)\n'
        source = method_replace(source, 'OvnNbSynchronizer', 'do_sync', old,
            old+'        if self.mode == ovn_const.OVN_DB_SYNC_MODE_REPAIR:\n'
                '            management_guard.repair_ports(\n'
                '                self.ovn_nb_api, self.core_plugin, ctx)\n')
    else:
        raise ValueError('Unknown source kind')
    ast.parse(source)
    return source


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-packages', required=True)
    args = parser.parse_args()
    root = Path(args.site_packages)/'neutron/plugins/ml2/drivers/ovn/mech_driver/ovsdb'
    targets = [(root/'ovn_client.py', 'client'), (root/'ovn_db_sync.py', 'sync')]
    # Validate both before changing either file. A failed image layer is never
    # promoted, and this tool is not for editing live installed services.
    rendered = [(path, transform(path.read_text(), kind)) for path, kind in targets]
    for path, source in rendered:
        path.write_text(source)
