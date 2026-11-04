#!/usr/bin/env python3
"""Compare live capacity alerts to the immutable authoritative VPC source."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import yaml

ALERTS=('VPCAcceleratedInterfaceCapacityLow','VPCAcceleratedInterfaceCapacityExhausted')
SOURCE='config/prometheus/networkinterface_alerts.yaml'


def assert_alerts(live,expected):
    def indexed(value):
        return {r['alert']:r for group in value['spec']['groups'] for r in group['rules'] if 'alert' in r}
    actual=indexed(live)
    required=indexed(expected)
    for name in ALERTS:
        if name not in actual or name not in required:
            raise ValueError('required capacity alert missing: '+name)
        if actual[name]!=required[name]:
            fields=sorted(k for k in set(actual[name])|set(required[name]) if actual[name].get(k)!=required[name].get(k))
            raise ValueError(name+' differs from locked VPC authority: '+', '.join(fields))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-repo',type=Path,required=True)
    parser.add_argument('--lock',type=Path,required=True)
    args=parser.parse_args()
    revision=yaml.safe_load(args.lock.read_text())['spec']['sourceRevision']
    if len(revision)!=40 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('full immutable VPC source revision required')
    subprocess.run(['git','-C',str(args.source_repo),'diff','--quiet',revision,'HEAD','--',SOURCE],check=True)
    subprocess.run(['git','-C',str(args.source_repo),'diff','--quiet','HEAD','--',SOURCE],check=True)
    expected=yaml.safe_load(subprocess.check_output(['git','-C',str(args.source_repo),'show',revision+':'+SOURCE],text=True))
    assert_alerts(json.load(sys.stdin),expected)
    print('VPC capacity alerts match locked authoritative source '+revision)


if __name__=='__main__':main()
