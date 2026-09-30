"""Real private OVN datapath contract, invoked only by development reconciler.

Requires an empty network namespace on the development utility and extracted,
pinned OVS/OVN tools. This is not Nova VM or production Neutron acceptance.
"""
import json
import os
from pathlib import Path
import socket
import selectors
import subprocess as sp
import sys
import tempfile
import time

from dcn_management_guard import compile_policy


def main():
    assert socket.gethostname() == 'dcn-1b-utility-0'
    assert os.readlink('/proc/self/ns/net') != os.readlink('/proc/1/ns/net')
    tools = Path(sys.argv[1]).resolve()
    mode = sys.argv[2]
    assert mode in ('allow-stateless', 'allow-related'), 'Explicit supported ACL mode required'
    with tempfile.TemporaryDirectory(prefix='guard-packet-') as directory:
        root = Path(directory)
        env = dict(os.environ, PATH=':'.join(str(tools/p) for p in
                   ('usr/bin', 'usr/sbin', 'usr/lib/openvswitch-switch'))+':'+os.environ['PATH'],
                   LD_LIBRARY_PATH=str(tools/'usr/lib/x86_64-linux-gnu'),
                   OVS_RUNDIR=str(root), OVS_LOGDIR=str(root),
                   OVN_RUNDIR=str(root), OVN_LOGDIR=str(root))
        children, logs = [], []

        def run(*args):
            return sp.check_output(args, env=env, text=True, stderr=sp.STDOUT, timeout=20).strip()

        def start(name, *args):
            log = (root/(name+'.log')).open('w+')
            logs.append(log)
            child = sp.Popen(args, env=env, stdout=log, stderr=log)
            children.append(child)
            return child

        def wait_for(predicate):
            deadline = time.monotonic()+20
            while not predicate():
                assert all(c.poll() is None for c in children), 'Private process exited'
                if time.monotonic() >= deadline:
                    raise RuntimeError('Private datapath readiness timeout')
                time.sleep(.05)

        def ovs(*args):
            return run('ovs-vsctl', '--db=unix:'+str(root/'ovs.sock'), '--timeout=10', *args)

        def nb(*args):
            return run('ovn-nbctl', '--db=unix:'+str(root/'nb.sock'), '--timeout=15', *args)

        def inside(pid, *args):
            return run('nsenter', '-t', str(pid), '-n', *args)

        try:
            assert [i['ifname'] for i in json.loads(run('ip', '-j', 'link'))] == ['lo']
            for name, schema in [('ovs', 'openvswitch/vswitch'), ('nb', 'ovn/ovn-nb'), ('sb', 'ovn/ovn-sb')]:
                run('ovsdb-tool', 'create', str(root/(name+'.db')), str(tools/('usr/share/'+schema+'.ovsschema')))
                start(name, 'ovsdb-server', str(root/(name+'.db')), '--remote=punix:'+str(root/(name+'.sock')),
                      '--unixctl='+str(root/(name+'.ctl')), '--no-chdir')
            wait_for(lambda: all((root/(name+'.sock')).exists() for name in ('ovs', 'nb', 'sb')))
            ovs('--no-wait', 'init')
            nb('init')
            run('ip', 'link', 'set', 'lo', 'up')
            start('vswitch', 'ovs-vswitchd', 'unix:'+str(root/'ovs.sock'), '--unixctl='+str(root/'vswitch.ctl'), '--no-chdir')
            ovs('add-br', 'br-int', '--', 'set', 'Bridge', 'br-int', 'fail_mode=secure')
            ovs('set', 'Open_vSwitch', '.', 'external_ids:system-id=guard-private-chassis',
                'external_ids:ovn-remote=unix:'+str(root/'sb.sock'),
                'external_ids:ovn-encap-type=geneve', 'external_ids:ovn-encap-ip=127.0.0.1')
            start('northd', 'ovn-northd', '--ovnnb-db=unix:'+str(root/'nb.sock'),
                  '--ovnsb-db=unix:'+str(root/'sb.sock'), '--unixctl='+str(root/'northd.ctl'), '--no-chdir')
            start('controller', 'ovn-controller', 'unix:'+str(root/'ovs.sock'),
                  '--pidfile='+str(root/'controller.pid'), '--no-chdir')
            nb('ls-add', 'guard-test')
            endpoints = {}
            for index, name in enumerate(('client', 'server'), 1):
                child = start(name, 'unshare', '--net', 'sleep', '300')
                wait_for(lambda: os.readlink('/proc/%d/ns/net' % child.pid) != os.readlink('/proc/self/ns/net'))
                endpoints[name] = child.pid
                mac = '02:00:00:00:00:0'+str(index)
                run('ip', 'link', 'add', name, 'type', 'veth', 'peer', 'name', name+'-nic')
                run('ip', 'link', 'set', name+'-nic', 'netns', str(child.pid))
                run('ip', 'link', 'set', name, 'up')
                inside(child.pid, 'ip', 'link', 'set', name+'-nic', 'address', mac)
                inside(child.pid, 'ip', 'addr', 'add', '198.18.40.'+str(index)+'/24', 'dev', name+'-nic')
                inside(child.pid, 'ip', 'link', 'set', name+'-nic', 'up')
                nb('lsp-add', 'guard-test', name)
                nb('lsp-set-addresses', name, mac+' 198.18.40.'+str(index))
                ovs('add-port', 'br-int', name, '--', 'set', 'Interface', name, 'external_ids:iface-id='+name)
            inside(endpoints['server'], 'ip', 'addr', 'add', '198.18.40.3/24', 'dev', 'server-nic')
            nb('lsp-set-addresses', 'server', '02:00:00:00:00:02 198.18.40.2 198.18.40.3')
            # Strong tenant allow is deliberately present; provider deny must win.
            nb('acl-add', 'guard-test', 'from-lport', '1003', 'ip4', mode)
            echo = ('import socket,threading\n'
                    'def serve(c):\n'
                    ' try:\n'
                    '  while True:\n'
                    '   d=c.recv(64)\n'
                    '   if not d:break\n'
                    '   c.sendall(d)\n'
                    ' finally:c.close()\n'
                    's=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);'
                    's.bind(("0.0.0.0",443));s.listen()\n'
                    'while True:\n c,a=s.accept();threading.Thread(target=serve,args=(c,),daemon=True).start()\n')
            start('echo', 'nsenter', '-t', str(endpoints['server']), '-n', 'python3', '-c', echo)
            probe = ('import socket,sys\n'
                     'with socket.create_connection((sys.argv[1],443),timeout=2) as s:\n'
                     ' s.settimeout(2);s.sendall(b"guard-probe");assert s.recv(64)==b"guard-probe"\n')

            def connect(address):
                return inside(endpoints['client'], 'python3', '-c', probe, address)

            nb('--wait=hv', 'sync')
            connect('198.18.40.2')
            connect('198.18.40.3')
            persistent_source = (
                'import socket,sys\n'
                's=socket.create_connection(("198.18.40.2",443),timeout=2);s.settimeout(2)\n'
                'for line in sys.stdin:\n'
                ' try:\n'
                '  s.sendall(b"existing");d=s.recv(64)\n'
                '  assert d==b"existing"\n'
                '  print("CONNECTED",flush=True)\n'
                ' except socket.timeout:print("BLOCKED",flush=True)\n')
            persistent = sp.Popen(['nsenter', '-t', str(endpoints['client']), '-n',
                                   'python3', '-c', persistent_source], env=env,
                                  stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE, text=True)
            children.append(persistent)

            def existing_connection(expected):
                persistent.stdin.write('probe\n')
                persistent.stdin.flush()
                with selectors.DefaultSelector() as selector:
                    selector.register(persistent.stdout, selectors.EVENT_READ)
                    assert selector.select(timeout=5), 'Persistent TCP probe did not complete'
                assert persistent.stdout.readline().strip() == expected, 'Unexpected established-flow result'

            existing_connection('CONNECTED')
            policy = compile_policy(['1'*32], ['198.18.40.2/32'])['1'*32]
            nb('pg-add', policy['name'], 'client')
            for acl in policy['acls']:
                nb('--type=port-group', 'acl-add', policy['name'], acl['direction'],
                   str(acl['priority']), acl['match'], acl['action'])
            nb('--wait=hv', 'sync')
            connect('198.18.40.3')
            existing_connection('BLOCKED')
            try:
                connect('198.18.40.2')
            except sp.CalledProcessError as error:
                assert 'TimeoutError' in error.output, error.output
            else:
                raise AssertionError('Management destination was not blocked')
            nb('pg-del', policy['name'])
            nb('--wait=hv', 'sync')
            connect('198.18.40.2')
            print(json.dumps({'tenant_acl_mode': mode, 'real_ovn_tcp_deny': True, 'allowed_destination_survives': True,
                              'baseline_and_restored': True, 'established_connection_denied': True,
                              'native_neutron_and_vm_acceptance': 'not-tested'}))
        except Exception as error:
            if isinstance(error, sp.CalledProcessError):
                print(error.output, file=sys.stderr)
            for log in logs:
                log.flush()
                print(Path(log.name).name, Path(log.name).read_text()[-3000:], file=sys.stderr)
            raise
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except sp.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
            for log in logs:
                log.close()


if __name__ == '__main__':
    main()
