"""Private Linux namespace + real OVS acceptance; no production interfaces.

Invoked by the production repository's isolated development reconciler.
Inputs: extracted tool root, exact rendered initializer. No NFS/VM claims.
"""
import json
import os
from pathlib import Path
import socket
import subprocess as sp
import sys
import tempfile
import time


def main():
    assert socket.gethostname() == 'dcn-1b-utility-0'
    assert os.readlink('/proc/self/ns/net') != os.readlink('/proc/1/ns/net')
    tools, source = map(Path, sys.argv[1:])
    script = source.read_text()
    start = script.index('# BEGIN operator-selected')
    end = script.index('ovs-vsctl set open . external-ids:ovn-bridge-mappings=', start)
    section = script[start:script.index('\n', end)]
    with tempfile.TemporaryDirectory(prefix='nfs-kernel-db-') as directory:
        root = Path(directory)
        env = dict(os.environ, PATH=str(tools/'usr/bin')+':'+os.environ['PATH'],
                   LD_LIBRARY_PATH=str(tools/'usr/lib/x86_64-linux-gnu'),
                   OVS_RUNDIR=str(root), OVS_LOGDIR=str(root), OVS_DBDIR=str(root),
                   NODE_NAME='dcn-1b-compute-1')
        children = []
        def run(*args, **kwargs):
            p = sp.run(args, env=env, text=True, capture_output=True, timeout=20, **kwargs)
            if p.returncode:
                raise RuntimeError((args, p.returncode, p.stdout, p.stderr))
            return p.stdout.strip()
        def ovs(*args):
            return run('ovs-vsctl', '--timeout=10', *args)
        try:
            assert [i['ifname'] for i in json.loads(run('ip', '-j', 'link'))] == ['lo']
            run('ip', 'link', 'add', 'dcn-storage0', 'type', 'dummy')
            run('ip', 'link', 'set', 'dcn-storage0', 'up')
            run('ip', 'link', 'add', 'link', 'dcn-storage0', 'name', 'dcn-nfs-svc',
                'type', 'vlan', 'id', '181')
            run('ip', 'link', 'set', 'dcn-nfs-svc', 'addrgenmode', 'none')
            run('ip', 'link', 'set', 'dcn-nfs-svc', 'up')
            run('ovsdb-tool', 'create', str(root/'conf.db'),
                str(tools/'usr/share/openvswitch/vswitch.ovsschema'))
            db = sp.Popen([str(tools/'usr/sbin/ovsdb-server'), str(root/'conf.db'),
                '--remote=punix:'+str(root/'db.sock'), '--unixctl='+str(root/'db.ctl'),
                '--no-chdir'], env=env, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
            children.append(db)
            for _ in range(100):
                assert db.poll() is None
                if (root/'db.sock').exists():
                    break
                time.sleep(.02)
            run('ovs-vsctl', '--no-wait', 'init')
            switch = sp.Popen([str(tools/'usr/lib/openvswitch-switch/ovs-vswitchd'),
                'unix:'+str(root/'db.sock'), '--unixctl='+str(root/'switch.ctl'),
                '--no-chdir', '--log-file='+str(root/'switch.log')], env=env,
                stdout=sp.DEVNULL, stderr=sp.DEVNULL)
            children.append(switch)
            ovs('add-br', 'br-ex')
            ovs('add-br', 'br-int')
            assert switch.poll() is None
            def initialize(ok=True):
                p = sp.run(['bash'], input='set -e\nbridge_mappings=external-rack-2:br-ex\n'+section,
                           env=env, text=True, capture_output=True, timeout=30)
                assert (p.returncode == 0) == ok, (p.returncode, p.stdout, p.stderr)
            initialize()
            initialize()
            assert ovs('port-to-br', 'dcn-nfs-svc') == 'br-nfs'
            assert not run('ip', '-o', 'addr', 'show', 'dev', 'br-nfs')
            assert not run('ip', '-o', 'addr', 'show', 'dev', 'dcn-nfs-svc')
            ovs('add-port', 'br-nfs', 'patch-local', '--', 'set', 'Interface', 'patch-local',
                'type=patch', 'options:peer=patch-peer', '--', 'set', 'Port', 'patch-local',
                'external_ids:ovn-localnet-port=provnet-test')
            ovs('add-port', 'br-int', 'patch-peer', '--', 'set', 'Interface', 'patch-peer',
                'type=patch', 'options:peer=patch-local', '--', 'set', 'Port', 'patch-peer',
                'external_ids:ovn-localnet-port=provnet-test')
            initialize()
            run('ip', 'addr', 'add', '198.18.0.1/24', 'dev', 'dcn-nfs-svc')
            initialize(ok=False)
            assert '198.18.0.1/24' in run('ip', '-o', 'addr', 'show', 'dev', 'dcn-nfs-svc')
            run('ip', 'addr', 'del', '198.18.0.1/24', 'dev', 'dcn-nfs-svc')
            initialize()
            assert ovs('get', 'Open_vSwitch', '.', 'external_ids:ovn-bridge-mappings').strip('"') == 'external-rack-2:br-ex,managed-nfs:br-nfs'
            print(json.dumps({'real_kernel_vlan': 'pass', 'real_ovs_switch': 'pass',
                'repeat_init': 'pass', 'addressless': 'pass', 'patch_pair': 'pass',
                'addressed_interface_rejected_and_preserved': 'pass',
                'nfs_vm_acceptance': 'not performed'}))
        except Exception:
            if (root/'switch.log').exists():
                print((root/'switch.log').read_text()[-6000:], file=sys.stderr)
            raise
        finally:
            for child in reversed(children):
                child.terminate()
                try:
                    child.wait(timeout=5)
                except sp.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == '__main__':
    main()
