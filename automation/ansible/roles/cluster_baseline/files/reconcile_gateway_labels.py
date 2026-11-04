#!/usr/bin/env python3
"""Inventory-driven gateway aliases only; runtime CMS is a separate contract."""
import argparse
import json
import re
import subprocess

LABELS=('openstack-network-gateway','openstack-ovn-gateway')


def require_roles(roles):
    if not isinstance(roles,dict) or not roles:raise ValueError('explicit managed roles are required')
    for name,values in roles.items():
        if not isinstance(name,str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',name):
            raise ValueError('invalid managed node name')
        if (not isinstance(values,list) or not values or
                not all(isinstance(value,str) and re.fullmatch(r'[a-z][a-z0-9_]*',value) for value in values)
                or len(set(values))!=len(values)):
            raise ValueError('explicit unique node_roles are required for every managed node')


def plan(roles,document):
    require_roles(roles)
    if document.get('kind') not in ('NodeList','List'):raise ValueError('expected a Kubernetes node list')
    nodes={}
    for node in document['items']:
        metadata=node['metadata'];name=metadata['name']
        if name in nodes:raise ValueError('ambiguous live node identity')
        nodes[name]=node
    result=[]
    for name in sorted(roles):
        if name not in nodes:raise ValueError('managed node is missing')
        node=nodes[name];metadata=node['metadata']
        if node.get('kind')!='Node' or not metadata.get('uid') or not metadata.get('resourceVersion'):
            raise ValueError('missing live node UID/resourceVersion')
        labels=metadata.get('labels',{})
        if not isinstance(labels,dict):raise ValueError('invalid live labels')
        enabled='ovn_gateway' in roles[name]
        operations=[]
        for label in LABELS:
            if label in labels and labels[label]!='enabled':raise ValueError('unexpected gateway alias value')
            path='/metadata/labels/'+label
            if enabled and label not in labels:
                operations.append({'op':'add','path':path,'value':'enabled'})
            elif not enabled and label in labels:
                operations.extend([{'op':'test','path':path,'value':'enabled'},
                                   {'op':'remove','path':path}])
        if operations:
            prefix=[{'op':'test','path':'/metadata/uid','value':metadata['uid']},
                    {'op':'test','path':'/metadata/resourceVersion','value':metadata['resourceVersion']}]
            # JSON Patch needs the labels object on a genuinely fresh Node.
            if enabled and 'labels' not in metadata:
                prefix.append({'op':'add','path':'/metadata/labels','value':{}})
            result.append({'node':name,'desired_gateway':enabled,'uid':metadata['uid'],
                           'resource_version':metadata['resourceVersion'],'patch':prefix+operations})
    return result


def kube(*args):
    result=subprocess.run(['kubectl','--request-timeout=20s',*args],capture_output=True,text=True,timeout=30)
    if result.returncode:raise RuntimeError('gateway label Kubernetes operation failed: '+result.stderr.strip())
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roles-json',required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true');mode.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    roles=json.loads(args.roles_json);require_roles(roles)
    changes=plan(roles,kube('get','nodes','-o','json'))
    for change in changes:
        command=['patch','node',change['node'],'--type=json','-p',json.dumps(change['patch']),'-o','json']
        if args.check:command.append('--dry-run=server')
        result=kube(*command)
        if result['metadata']['uid']!=change['uid']:raise RuntimeError('gateway patch returned a different node')
    if args.apply and plan(roles,kube('get','nodes','-o','json')):
        raise RuntimeError('gateway alias verification failed')
    print(json.dumps({'changed':bool(changes),'check_mode':args.check,'changes':changes,
        'runtime_cms_reconciled':False,'data_plane_labels_modified':False}))


if __name__=='__main__':main()
