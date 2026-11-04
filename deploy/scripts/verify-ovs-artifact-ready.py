#!/usr/bin/env python3
"""Read-only OVS convergence gate for OnDelete; never replace a Pod."""
import argparse
import json
from pathlib import Path
import subprocess
import time

import yaml

NAMES={'openvswitch-db','openvswitch-vswitchd','openvswitch-db-perms','openvswitch-vswitchd-modules'}


def validate(daemonset,pods,image,preflight=False):
    """False means readiness pending; wrong provenance requires maintenance, not a retry."""
    if not daemonset:
        if preflight:return True
        raise ValueError('OVS DaemonSet is absent')
    uid=daemonset['metadata']['uid']
    template=daemonset['spec']['template']['spec']
    expected={c['name']:c['image'] for c in template['containers']+template.get('initContainers',[]) if c['name'] in NAMES}
    if set(expected)!=NAMES or set(expected.values())!={image}:
        raise ValueError('OVS template needs qualified artifact maintenance before reconciliation')
    selected=[p for p in pods if any(r.get('kind')=='DaemonSet' and r.get('uid')==uid and r.get('controller') is True
        for r in p['metadata'].get('ownerReferences',[]))]
    live=[p for p in selected if not p['metadata'].get('deletionTimestamp')]
    for pod in live:
        spec=pod['spec']
        images={c['name']:c['image'] for c in spec['containers']+spec.get('initContainers',[]) if c['name'] in NAMES}
        if images!=expected:
            raise ValueError('OVS Pod artifact differs; staged template is not runtime convergence')
        statuses={c['name']:c for c in pod.get('status',{}).get('containerStatuses',[])
                  +pod.get('status',{}).get('initContainerStatuses',[])}
        for name in NAMES:
            status=statuses.get(name,{})
            if status.get('imageID') and not status['imageID'].endswith('@'+image.split('@')[1]):
                raise ValueError('running OVS artifact does not match the approved digest')
            if status.get('state',{}).get('terminated',{}).get('exitCode',0)!=0:
                raise ValueError('OVS container failed')
    if preflight:return True
    if daemonset['spec'].get('updateStrategy')!={'type':'OnDelete'}:
        raise ValueError('OVS template replacement strategy changed')
    status=daemonset.get('status',{});desired=status.get('desiredNumberScheduled',0)
    if not desired:return False
    if status.get('observedGeneration',0)<daemonset['metadata']['generation']:return False
    if any(status.get(k,0)!=desired for k in ('updatedNumberScheduled','numberReady','numberAvailable')):return False
    if status.get('numberMisscheduled',0) or len(live)!=desired or len(selected)!=desired:return False
    if len({p['spec'].get('nodeName') for p in live})!=desired:return False
    for pod in live:
        if pod.get('status',{}).get('phase')!='Running':return False
        if not any(c.get('type')=='Ready' and c.get('status')=='True' for c in pod['status'].get('conditions',[])):return False
        statuses={c['name']:c for c in pod['status'].get('containerStatuses',[])+pod['status'].get('initContainerStatuses',[])}
        if any(not statuses.get(name,{}).get('imageID','').endswith('@'+image.split('@')[1]) for name in NAMES):return False
    return True


def query(namespace):
    def get(*args):
        result=subprocess.run(['kubectl','--request-timeout=15s','-n',namespace,*args],
            text=True,capture_output=True,timeout=25,check=True)
        return json.loads(result.stdout) if result.stdout.strip() else None
    ds=get('get','daemonset','openvswitch','--ignore-not-found','-o','json')
    if not ds:return None,[]
    selector=','.join(k+'='+v for k,v in sorted(ds['spec']['selector']['matchLabels'].items()))
    return ds,get('get','pods','-l',selector,'-o','json')['items']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',default='openstack')
    parser.add_argument('--preflight',action='store_true')
    parser.add_argument('--timeout',type=int,default=900)
    args=parser.parse_args()
    assert 1<=args.timeout<=900
    values=yaml.safe_load((Path(__file__).resolve().parents[1]/'values/site/openvswitch.yaml').read_text())
    image=values['images']['tags']['openvswitch_vswitchd']
    assert '@sha256:' in image and values['images']['tags']['openvswitch_db_server']==image
    deadline=time.monotonic()+args.timeout
    while True:
        ds,pods=query(args.namespace)
        if validate(ds,pods,image,args.preflight):
            print(json.dumps({'ovs_artifact_preflight' if args.preflight else 'ovs_artifact_ready':True,
                              'production_mutations':0}));return
        if time.monotonic()>deadline:raise TimeoutError('OVS artifact readiness is incomplete')
        time.sleep(2)


if __name__=='__main__':main()
