#!/usr/bin/env python3
"""Keep exactly one share-manager during Helm template replacement.

Used by both Manila render-only checks and the authoritative reconciler.
Never modify other workloads or print rejected input in errors.
"""
import copy
import sys

import yaml


def render(objects):
    result = copy.deepcopy(objects)
    matches = [obj for obj in result if isinstance(obj, dict)
               and obj.get('kind') == 'Deployment'
               and obj.get('metadata', {}).get('name') == 'manila-share']
    if len(matches) != 1:
        raise ValueError('Exactly one Manila share Deployment required')
    share = matches[0]
    if share.get('apiVersion') != 'apps/v1' or share.get('spec', {}).get('replicas') != 1:
        raise ValueError('Single share-manager deployment contract required')
    share['spec']['strategy'] = {'type': 'Recreate'}
    return result


def main():
    try:
        data = sys.stdin.read(32*1024*1024+1)
        if len(data) > 32*1024*1024:
            raise ValueError('Oversized input')
        objects = list(yaml.safe_load_all(data))
        output = render(objects)
    except Exception:
        raise SystemExit('Manila share post-render failed; configuration withheld') from None
    sys.stdout.write(yaml.safe_dump_all(output, sort_keys=False))


if __name__ == '__main__':
    main()
